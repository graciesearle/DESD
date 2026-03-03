from collections import OrderedDict
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import customer_required
from cart.models import Cart, CartItem
from cart.views import _get_or_create_active_cart, _validate_cart_items

from .forms import CheckoutForm
from .models import Notification, Order, OrderItem, Payment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_cart_producer(cart):
    """
    Returns the single producer (User instance) for all items in the cart,
    or None if the cart is empty or has items from multiple producers.
    """
    producer_ids = (
        cart.items
        .values_list("product__producer", flat=True)
        .distinct()
    )
    if len(producer_ids) != 1:
        return None
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.get(pk=producer_ids[0])


def _build_checkout_context(cart, producer, form=None):
    """
    Build the template context shared by GET and POST of the checkout view.
    """
    commission_rate = getattr(settings, "COMMISSION_RATE", Decimal("0.05"))

    items = (
        cart.items
        .select_related("product", "product__farm")
        .order_by("added_at")
    )

    item_data = []
    subtotal = Decimal("0.00")
    for ci in items:
        line_total = ci.product.price * ci.quantity
        item_data.append({
            "name": ci.product.name,
            "unit_price": ci.product.price,
            "quantity": ci.quantity,
            "unit": ci.product.unit,
            "line_total": line_total,
            "image_url": (
                ci.product.image.url
                if ci.product.image
                else "https://placehold.co/80x80?text=No+Image"
            ),
        })
        subtotal += line_total

    commission = (subtotal * commission_rate).quantize(Decimal("0.01"))
    total = subtotal  # Commission is included, not added on top
    producer_payment = (total - commission).quantize(Decimal("0.01"))

    # Producer lead time
    try:
        lead_time = producer.producer_profile.lead_time_hours
    except Exception:
        lead_time = 48

    if form is None:
        # Pre-fill from customer profile when available
        initial = {}
        try:
            cp = cart.user.customer_profile
            initial["delivery_address"] = cp.delivery_address
            initial["delivery_postcode"] = cp.postcode
        except Exception:
            pass
        form = CheckoutForm(initial=initial, lead_time_hours=lead_time)

    try:
        producer_name = producer.producer_profile.business_name
    except Exception:
        producer_name = producer.email

    return {
        "form": form,
        "cart": cart,
        "items": item_data,
        "producer": producer,
        "producer_name": producer_name,
        "subtotal": subtotal,
        "commission_rate_display": f"{int(commission_rate * 100)}%",
        "commission": commission,
        "total": total,
        "producer_payment": producer_payment,
        "commission_rate": commission_rate,
        "lead_time_hours": lead_time,
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@customer_required
def checkout(request):
    """
    GET  → render checkout page with order summary, address & date form.
    POST → validate, create order, process payment, redirect to confirmation.
    """
    cart = _get_or_create_active_cart(request.user)
    _validate_cart_items(request, cart)
    cart.refresh_from_db()

    if not cart.items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect("cart:cart_detail")

    producer = _get_cart_producer(cart)
    if producer is None:
        messages.error(
            request,
            "Your cart contains products from multiple producers. "
            "Please remove items so only one producer remains before checkout.",
        )
        return redirect("cart:cart_detail")

    # Determine lead time
    try:
        lead_time = producer.producer_profile.lead_time_hours
    except Exception:
        lead_time = 48

    # ---- GET ----
    if request.method != "POST":
        ctx = _build_checkout_context(cart, producer)
        return render(request, "orders/checkout.html", ctx)

    # ---- POST ----
    form = CheckoutForm(request.POST, lead_time_hours=lead_time)
    if not form.is_valid():
        ctx = _build_checkout_context(cart, producer, form=form)
        return render(request, "orders/checkout.html", ctx)

    # ---- Create order inside an atomic block ----
    commission_rate = getattr(settings, "COMMISSION_RATE", Decimal("0.05"))

    with transaction.atomic():
        order = Order(
            customer=request.user,
            producer=producer,
            delivery_address=form.cleaned_data["delivery_address"],
            delivery_postcode=form.cleaned_data["delivery_postcode"],
            delivery_date=form.cleaned_data["delivery_date"],
            commission_rate=commission_rate,
            # Placeholders — recalculated below
            subtotal=0,
            commission_amount=0,
            total=0,
            producer_payment=0,
        )
        order.save()  # generates order_number

        # Snapshot cart items into OrderItems
        for ci in cart.items.select_related("product"):
            OrderItem.objects.create(
                order=order,
                product=ci.product,
                product_name=ci.product.name,
                unit_price=ci.product.price,
                quantity=ci.quantity,
            )
            # Decrease stock
            ci.product.stock_quantity = max(
                0, ci.product.stock_quantity - ci.quantity
            )
            ci.product.save()

        # Recalculate totals from saved items
        order.calculate_financials()
        order.save()

        # ---- Process payment (test mode) ----
        payment = Payment.objects.create(
            order=order,
            amount=order.total,
            status=Payment.Status.SUCCESS,
            payment_method="test_card",
        )

        # Mark cart as ordered
        cart.status = "ordered"
        cart.save()

        # ---- Notify producer ----
        try:
            producer_name = producer.producer_profile.business_name
        except Exception:
            producer_name = producer.email

        Notification.objects.create(
            recipient=producer,
            order=order,
            notification_type=Notification.Type.NEW_ORDER,
            message=(
                f"You have a new order ({order.order_number}) worth "
                f"£{order.total} from {request.user.email}. "
                f"Delivery requested for {order.delivery_date.strftime('%d %b %Y')}."
            ),
        )

        # ---- Notify customer ----
        Notification.objects.create(
            recipient=request.user,
            order=order,
            notification_type=Notification.Type.ORDER_CONFIRMED,
            message=(
                f"Your order {order.order_number} has been placed successfully! "
                f"Total: £{order.total}. "
                f"Delivery date: {order.delivery_date.strftime('%d %b %Y')}."
            ),
        )

    messages.success(request, "Your order has been placed successfully!")
    return redirect("orders:order_confirmation", order_number=order.order_number)


@customer_required
def order_confirmation(request, order_number):
    """
    Displays the confirmation page immediately after a successful checkout.
    """
    order = get_object_or_404(
        Order.objects.select_related("producer", "payment"),
        order_number=order_number,
        customer=request.user,
    )
    items = order.items.all()

    try:
        producer_name = order.producer.producer_profile.business_name
    except Exception:
        producer_name = order.producer.email

    return render(request, "orders/order_confirmation.html", {
        "order": order,
        "items": items,
        "producer_name": producer_name,
    })


@login_required
def order_list(request):
    """
    Shows all orders for the logged-in user.
    Customers see their purchase orders; producers see orders they need to fulfil.
    """
    user = request.user

    if user.is_producer:
        orders = Order.objects.filter(producer=user).select_related("customer")
        template = "orders/producer_order_list.html"
    else:
        orders = Order.objects.filter(customer=user).select_related("producer")
        template = "orders/customer_order_list.html"

    return render(request, template, {"orders": orders})


@login_required
def order_detail(request, order_number):
    """
    Detailed view of a single order.
    Accessible by both the customer who placed it and the producer who fulfils it.
    """
    order = get_object_or_404(
        Order.objects.select_related("customer", "producer", "payment"),
        order_number=order_number,
    )

    # Only the customer or the producer may view
    if request.user != order.customer and request.user != order.producer:
        messages.error(request, "You don't have permission to view this order.")
        return redirect("orders:order_list")

    items = order.items.all()
    try:
        producer_name = order.producer.producer_profile.business_name
    except Exception:
        producer_name = order.producer.email

    try:
        customer_name = order.customer.customer_profile.full_name
    except Exception:
        customer_name = order.customer.email

    return render(request, "orders/order_detail.html", {
        "order": order,
        "items": items,
        "producer_name": producer_name,
        "customer_name": customer_name,
        "is_producer_view": request.user == order.producer,
    })
