from collections import OrderedDict, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import stripe
import csv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Case, When, IntegerField
from django.db.models.functions import Greatest
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string, get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST

from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from accounts.decorators import customer_required, producer_required, admin_required
from cart.models import Cart, CartItem
from cart.views import (
    _find_alternative_products,
    _format_alternative_suggestions,
    _get_or_create_active_cart,
    _is_product_purchasable,
    _store_alternative_suggestions_in_session,
    _validate_cart_items,
)
from products.models import Product

from .forms import CheckoutForm, ProducerDeliveryForm
from .models import (
    Notification, Order, OrderItem, Payment, ProducerOrder,
    get_producer_display_name,
)
from .serializers import ProducerSubOrderSerializer
from .services.financial_reporting import (
    aggregate_financial_metrics,
    generate_commission_accounting_csv,
    generate_commission_csv,
)

User = get_user_model()



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_cart_by_producer(cart):
    """
    Group cart items by their producer (User instance).

    Returns an ``OrderedDict`` mapping each producer ``User`` instance
    to a list of ``CartItem`` objects for that producer. This helper
    does not compute any per-producer or grand totals.
    """
    items = (
        cart.items
        .select_related(
            "product", "product__producer", "product__producer__producer_profile",
            "product__farm",
        )
        .order_by("product__producer__email", "added_at")
    )

    by_producer = OrderedDict()
    for ci in items:
        by_producer.setdefault(ci.product.producer, []).append(ci)

    return by_producer


def _build_checkout_context(cart, request, checkout_form=None,
                            producer_forms=None, by_producer=None):
    """
    Build the template context shared by GET and POST of the checkout view.
    Supports multi-vendor carts by grouping items per producer.

    Accepts an optional pre-computed ``by_producer`` dict so the caller
    can avoid a redundant database query when the grouping has already
    been fetched (e.g. during POST validation).
    """
    commission_rate = getattr(settings, "COMMISSION_RATE", Decimal("0.05"))

    # Reuse the grouping if the caller already computed it.
    if by_producer is None:
        by_producer = _group_cart_by_producer(cart)

    # ---------- per-producer data ----------
    producer_sections = []
    grand_subtotal = Decimal("0.00")

    for producer, cart_items in by_producer.items():
        try:
            lead_time = producer.producer_profile.lead_time_hours
        except AttributeError:
            lead_time = 48

        producer_name = get_producer_display_name(producer)

        item_data = []
        section_subtotal = Decimal("0.00")
        for ci in cart_items:
            line_total = ci.product.price * ci.quantity
            item_data.append({
                "product_id": ci.product_id,
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
            section_subtotal += line_total

        grand_subtotal += section_subtotal

        # Reuse provided form on POST; create fresh on GET
        if producer_forms and producer.id in producer_forms:
            form = producer_forms[producer.id]
        else:
            form = ProducerDeliveryForm(
                producer_id=producer.id,
                producer_name=producer_name,
                lead_time_hours=lead_time,
            )

        producer_sections.append({
            "producer": producer,
            "producer_name": producer_name,
            "lead_time_hours": lead_time,
            "items": item_data,
            "subtotal": section_subtotal,
            "form": form,
        })

    grand_commission = (grand_subtotal * commission_rate).quantize(Decimal("0.01"))
    grand_total = grand_subtotal
    grand_producer_payment = (grand_total - grand_commission).quantize(Decimal("0.01"))

    # ---------- shared checkout form ----------
    if checkout_form is None:
        initial = {}
        try:
            cp = cart.user.customer_profile
            initial["delivery_address"] = cp.delivery_address
            initial["delivery_postcode"] = cp.postcode
        except AttributeError:
            pass
        checkout_form = CheckoutForm(initial=initial)

    return {
        "form": checkout_form,
        "cart": cart,
        "producer_sections": producer_sections,
        "subtotal": grand_subtotal,
        "commission_rate_display": f"{int(commission_rate * 100)}%",
        "commission": grand_commission,
        "total": grand_total,
        "producer_payment": grand_producer_payment,
        "commission_rate": commission_rate,
        "is_multi_vendor": len(producer_sections) > 1,
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@customer_required
def checkout(request):
    """
    GET  → render checkout page with per-producer sections + shared address.
    POST → validate, create Order + ProducerOrders, process payment, redirect to stripe.

    Supports any number of producers in the cart (single or multi-vendor).
    """
    cart = _get_or_create_active_cart(request.user)
    _validate_cart_items(request, cart)
    cart.refresh_from_db()

    if not cart.items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect("cart:cart_detail")

    # Group cart items by producer once — reused by both the context
    # builder and the order-creation logic so we don't query twice.
    by_producer = _group_cart_by_producer(cart)
    commission_rate = getattr(settings, "COMMISSION_RATE", Decimal("0.05"))

    # ---- GET ----
    if request.method != "POST":
        ctx = _build_checkout_context(cart, request, by_producer=by_producer)
        return render(request, "orders/checkout.html", ctx)

    # ---- POST ----
    checkout_form = CheckoutForm(request.POST)

    # Build per-producer delivery forms from POST data
    producer_forms = {}   # producer.id → form
    for producer in by_producer:
        try:
            lead_time = producer.producer_profile.lead_time_hours
        except AttributeError:
            lead_time = 48

        form = ProducerDeliveryForm(
            request.POST,
            producer_id=producer.id,
            producer_name=get_producer_display_name(producer),
            lead_time_hours=lead_time,
        )
        producer_forms[producer.id] = form

    all_valid = checkout_form.is_valid()
    for pf in producer_forms.values():
        if not pf.is_valid():
            all_valid = False

    if not all_valid:
        ctx = _build_checkout_context(
            cart, request,
            checkout_form=checkout_form,
            producer_forms=producer_forms,
            by_producer=by_producer,
        )
        return render(request, "orders/checkout.html", ctx)

    # ---- Create order inside an atomic block ----
    insufficient_messages = []
    stripe_url = None

    try:
        with transaction.atomic():
            # Lock the product rows we're about to decrement so that two
            # concurrent checkouts can't both read the same stock value.
            # select_for_update() acquires a row-level lock until the
            # transaction commits.
            product_ids = [
                ci.product_id
                for items in by_producer.values()
                for ci in items
            ]
            locked_products = {
                p.pk: p
                for p in Product.objects.select_for_update().filter(pk__in=product_ids)
            }

            # Verify every item still has enough stock.  If not, bail out
            # with a user-friendly message rather than silently overselling.
            insufficient = []
            for cart_items in by_producer.values():
                for ci in cart_items:
                    current = locked_products[ci.product_id].stock_quantity
                    if current < ci.quantity:
                        alternatives_text = _format_alternative_suggestions(
                            ci.product, ci.quantity,
                        )
                        insufficient.append(
                            f'"{ci.product.name}" only has {current} in stock '
                            f'(you requested {ci.quantity}).{alternatives_text}'
                        )

            if insufficient:
                # Do not render while locks are held. Capture messages and
                # let the atomic block exit first so row locks are released.

                insufficient_messages = insufficient
            else:
                producers = list(by_producer.keys())

                # Create Parent Order
                order = Order(
                    customer=request.user,
                    delivery_address=checkout_form.cleaned_data["delivery_address"],
                    delivery_postcode=checkout_form.cleaned_data["delivery_postcode"],
                    commission_rate=commission_rate,
                    subtotal=0,
                    commission_amount=0,
                    total=0,
                    producer_payment=0,
                )
                order.save() # generates order_number

                # Create ProducerOrders and Items
                for producer, cart_items in by_producer.items():
                    pf = producer_forms[producer.id]
                    delivery_date = pf.cleaned_data["delivery_date"]

                    sub_order = ProducerOrder.objects.create(
                        order=order,
                        producer=producer,
                        delivery_date=delivery_date,
                        special_instructions=pf.cleaned_data.get("special_instructions", ""),
                        commission_rate=commission_rate,
                    )

                    # Snapshot cart items into OrderItems
                    for ci in cart_items:
                        OrderItem.objects.create(
                            order=order,
                            producer_order=sub_order,
                            product=ci.product,
                            product_name=ci.product.name,
                            unit_price=ci.product.price,
                            quantity=ci.quantity,
                        )

                        product = locked_products[ci.product_id]
                        new_stock = max(product.stock_quantity - ci.quantity, 0)
                        Product.objects.filter(pk=ci.product_id).update(stock_quantity=new_stock)

                        # Check threshold and alert
                        if new_stock <= product.low_stock_threshold and not product.low_stock_notified:
                            # Lock flag so we dont send 5 emails if they buy 5 items
                            Product.objects.filter(pk=ci.product_id).update(low_stock_notified=True)

                            Notification.objects.create(
                                recipient=product.producer,
                                notification_type=Notification.Type.LOW_STOCK,
                                message=f"Low Stock: {product.name} ({new_stock}) remaining",
                                product=product
                            )

                        # This isnt needed anymore (as the above approach does it, and is needed for notification logic.)
                        # Atomically decrease stock using an F-expression so
                        # concurrent requests can't read stale values.  Greatest()
                        # clamps the result to zero to prevent negative stock.
                        #Product.objects.filter(pk=ci.product_id).update(
                        #    stock_quantity=Greatest(
                        #        F("stock_quantity") - ci.quantity, 0
                        #    )
                        #)

                    sub_order.calculate_financials()
                    sub_order.save()

                order.calculate_financials()
                order.save()

                # Create Stripe Checkout
                stripe.api_key = settings.STRIPE_SECRET_KEY
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'gbp',
                            'product_data': {'name': f"Order {order.order_number}"},
                            'unit_amount': int(order.total * 100),  #Stripe uses pence
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url=request.build_absolute_uri(reverse(
                        'orders:payment_success')) + f"?session_id={{CHECKOUT_SESSION_ID}}&order_number={order.order_number}",
                    cancel_url=request.build_absolute_uri(
                        reverse('orders:payment_cancel')) + f"?order_number={order.order_number}",
                )
                stripe_url = checkout_session.url

    except stripe.error.StripeError as e:
        messages.error(request, f"Stripe gateway error: {e.user_message or str(e)}")
        return redirect('orders:checkout')
    except Exception as e:
        # Rolling back database if Stripe fails to connect
        messages.error(request, f"An unexpected error occurred: {str(e)}")
        return redirect('orders:checkout')

    if insufficient_messages:
        for msg in insufficient_messages:
            messages.error(request, msg)

    if insufficient_messages:
        ctx = _build_checkout_context(
            cart, request, checkout_form=checkout_form,
            producer_forms=producer_forms, by_producer=by_producer,
        )
        return render(request, "orders/checkout.html", ctx)

    # Send user to Stripe
    return redirect(stripe_url)


@customer_required
def payment_success(request):
    """Callback from Stripe after successful payment."""
    session_id = request.GET.get('session_id')
    order_number = request.GET.get('order_number')

    if not session_id or not order_number:
        return redirect('marketplace:product_list')

    stripe.api_key = settings.STRIPE_SECRET_KEY
    order = get_object_or_404(Order, order_number=order_number, customer=request.user)

    try:
        session = stripe.checkout.Session.retrieve(session_id)

        if session.payment_status == 'paid' and order.status == Order.Status.PENDING:
            with transaction.atomic():
                # Confirm Parent Order
                order.status = Order.Status.CONFIRMED
                order.save()

                # Confirm Producer Sub-Orders and notify them
                producer_names = []
                for so in order.sub_orders.all():
                    so.status = ProducerOrder.Status.CONFIRMED
                    so.save()
                    producer_names.append(get_producer_display_name(so.producer))

                    Notification.objects.create(
                        recipient=so.producer,
                        order=order,
                        notification_type=Notification.Type.NEW_ORDER,
                        message=f"You have a new paid order ({order.order_number}) worth £{so.subtotal}. Delivery requested for {so.delivery_date.strftime('%d %b %Y')}."
                    )

                # Record Payment
                Payment.objects.create(
                    order=order,
                    transaction_id=session.payment_intent or session.id,
                    amount=order.total,
                    status=Payment.Status.SUCCESS,
                    payment_method="stripe_card",
                )

                # Clear Cart
                cart = _get_or_create_active_cart(request.user)
                cart.status = "ordered"
                cart.save()

                #  Notify Customer
                Notification.objects.create(
                    recipient=request.user,
                    order=order,
                    notification_type=Notification.Type.ORDER_CONFIRMED,
                    message=f"Your order {order.order_number} has been placed successfully! Total: £{order.total}. Producers: {', '.join(producer_names)}."
                )

            messages.success(request, "Your order has been paid and confirmed!")
            return redirect("orders:order_confirmation", order_number=order.order_number)

    except stripe.error.StripeError as e:
        messages.error(request, f"Stripe verification error: {e.user_message or str(e)}")
    except Exception as e:
        messages.error(request, "Error verifying payment. Please contact support.")

    return redirect('orders:order_list')


@customer_required
def payment_cancel(request):
    """Callback from Stripe if the customer cancels the payment."""
    order_number = request.GET.get('order_number')
    if order_number:
        order = get_object_or_404(Order, order_number=order_number, customer=request.user)

        if order.status == Order.Status.PENDING:
            with transaction.atomic():
                # Restore stock safely using F expressions
                for item in order.items.all():
                    Product.objects.filter(pk=item.product_id).update(
                        stock_quantity=F('stock_quantity') + item.quantity
                    )
                # Cancel parent and sub-orders
                order.status = Order.Status.CANCELLED
                order.save()
                for so in order.sub_orders.all():
                    so.status = ProducerOrder.Status.CANCELLED
                    so.save()

    messages.warning(request, "Payment was cancelled. You have not been charged.")
    return redirect('orders:checkout')


@customer_required
def order_confirmation(request, order_number):
    """
    Displays the confirmation page immediately after a successful checkout.
    """
    order = get_object_or_404(
        Order.objects.select_related("payment").prefetch_related(
            "sub_orders__producer__producer_profile",
            "sub_orders__items",
        ),
        order_number=order_number,
        customer=request.user,
    )

    commission_rate = getattr(settings, "COMMISSION_RATE", Decimal("0.05"))

    # Build per-producer sections for the template
    producer_sections = []
    for so in order.sub_orders.all():
        producer_sections.append({
            "producer_name": get_producer_display_name(so.producer),
            "delivery_date": so.delivery_date,
            "special_instructions": so.special_instructions,
            "items": so.items.all(),
            "subtotal": so.subtotal,
            "producer_payment": so.producer_payment,
        })

    return render(request, "orders/order_confirmation.html", {
        "order": order,
        "producer_sections": producer_sections,
        "is_multi_vendor": len(producer_sections) > 1,
        "commission_rate_display": f"{int(commission_rate * 100)}%",
        "producer_rate_display": f"{int((1 - commission_rate) * 100)}%",
    })


def _add_active_tag(active_tags, current_params, param_key, label):
    """
    Helper function to generate active filter tags.
    Copies the GET parameters, removes the specific filter key and appends the new tag to the active_tags list.
    """
    p = current_params.copy()
    p.pop(param_key, None)
    active_tags.append({
        'label': label,
        'url': f"?{p.urlencode()}"
    })


def _mask_sensitive_identifier(value, keep=4):
    """Mask an identifier so only the final `keep` characters are visible."""
    if not value:
        return "-"
    value = str(value)
    if len(value) <= keep:
        return "*" * len(value)
    return f"{'*' * (len(value) - keep)}{value[-keep:]}"


def _format_payment_method_label(payment_method):
    """Turn storage-friendly payment method codes into display labels."""
    if not payment_method:
        return "Card"
    return str(payment_method).replace("_", " ").title()

STATUS_FLOW = {
    ProducerOrder.Status.PENDING: ProducerOrder.Status.CONFIRMED,
    ProducerOrder.Status.CONFIRMED: ProducerOrder.Status.DISPATCHED,
    ProducerOrder.Status.DISPATCHED: ProducerOrder.Status.DELIVERED,
}


def _sync_parent_order_status(order):
    """Keep parent order status aligned with child producer sub-order statuses."""
    statuses = list(order.sub_orders.values_list("status", flat=True))
    if not statuses:
        return

    if all(s == ProducerOrder.Status.CANCELLED for s in statuses):
        next_status = Order.Status.CANCELLED
    elif all(s == ProducerOrder.Status.DELIVERED for s in statuses):
        next_status = Order.Status.DELIVERED
    elif any(s in {ProducerOrder.Status.DISPATCHED, ProducerOrder.Status.DELIVERED} for s in statuses):
        next_status = Order.Status.DISPATCHED
    elif any(s == ProducerOrder.Status.CONFIRMED for s in statuses):
        next_status = Order.Status.CONFIRMED
    else:
        next_status = Order.Status.PENDING

    if order.status != next_status:
        old_status = order.get_status_display()
        order.status = next_status
        order._change_reason = (
            f"Auto-sync from producer sub-order status changes: "
            f"{old_status} -> {order.get_status_display()}"
        )
        order.save()


@producer_required
@require_POST
def producer_update_sub_order_status(request, sub_order_id):
    """Advance a producer's own sub-order status by one valid lifecycle step."""
    sub_order = get_object_or_404(
        ProducerOrder.objects.select_related("order", "order__customer"),
        pk=sub_order_id,
        producer=request.user,
    )

    target_status = request.POST.get("target_status")
    status_note = (request.POST.get("status_note") or "").strip()
    if len(status_note) > 250:
        status_note = status_note[:250]
    next_status = STATUS_FLOW.get(sub_order.status)

    if not next_status:
        messages.warning(request, "This order cannot be advanced any further.")
        return redirect("orders:order_list")

    if target_status != next_status:
        messages.error(
            request,
            "Invalid status transition. Order statuses must follow: "
            "Pending -> Confirmed -> Ready -> Delivered.",
        )
        return redirect("orders:order_list")

    old_label = sub_order.get_status_display()
    new_label = dict(ProducerOrder.Status.choices).get(next_status, next_status)

    with transaction.atomic():
        sub_order.status = next_status
        if status_note:
            sub_order._change_reason = (
                f"Producer status update: {old_label} -> {new_label}. "
                f"Note: {status_note}"
            )
        else:
            sub_order._change_reason = f"Producer status update: {old_label} -> {new_label}"
        sub_order.save()

        _sync_parent_order_status(sub_order.order)

        note_suffix = f" Note: {status_note}" if status_note else ""
        Notification.objects.create(
            recipient=sub_order.order.customer,
            order=sub_order.order,
            notification_type=Notification.Type.ORDER_STATUS_UPDATE,
            message=(
                f"Update for order {sub_order.order.order_number}: "
                f"{get_producer_display_name(sub_order.producer)} marked their items as {new_label}."
                f"{note_suffix}"
            ),
        )

    messages.success(request, f"Order status updated to {new_label}.")
    return redirect("orders:order_list")

@login_required
def order_list(request):
    """
    Shows all orders for the logged-in user.
    Customers see their purchase orders; producers see sub-orders they
    need to fulfil.
    """
    user = request.user

    if getattr(user, "is_producer", False):
        # Producers see their ProducerOrder sub-orders.
        sub_orders = (
            ProducerOrder.objects
            .filter(producer=user)
            .select_related("order", "order__customer", "order__customer__customer_profile")
            .prefetch_related("items")
        )

        # Capture Query Parameters
        filter_status = request.GET.get('status', '')
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')
        sort_by = request.GET.get('sort_by', 'date_asc') # Default to date ascension sorting.

        # To get the "Clear x" tags, copy GET parameters
        params = request.GET.copy()
        active_tags = [] 

        # Filter: Status
        if filter_status and filter_status in ProducerOrder.Status.values:
            sub_orders = sub_orders.filter(status=filter_status)
            status_label = dict(ProducerOrder.Status.choices).get(filter_status, filter_status)
            _add_active_tag(active_tags, params, 'status', f'Status: {status_label}')

        # Filter: Start Date
        if start_date:
            try:
                date.fromisoformat(start_date)
                sub_orders = sub_orders.filter(delivery_date__gte=start_date)
                _add_active_tag(active_tags, params, 'start_date', f'From: {start_date}')
            except ValueError:
                pass # Fail silently if user messes with URL date format.

        # Filter: End Date
        if end_date:
            try:
                date.fromisoformat(end_date)
                sub_orders = sub_orders.filter(delivery_date__lte=end_date)
                _add_active_tag(active_tags, params, 'end_date', f'To: {end_date}')
            except ValueError:
                pass

        # Sort
        if sort_by == 'date_desc':
            # Newest to Oldest (filter first by delivery date, if both have same, filter by created)
            sub_orders = sub_orders.order_by('-delivery_date', '-created_at')
            _add_active_tag(active_tags, params, 'sort_by', 'Sorted: Latest First')

        elif sort_by.startswith('status_'):
            # Extract status from sort_by string (e.g. "status_CONFIRMED" -> "CONFIRMED")
            target_status = sort_by.replace('status_', '')

            # Security: verify status exists in model choices
            if target_status in ProducerOrder.Status.values:
                sub_orders = sub_orders.order_by( # Priority sorting
                    Case(
                        When(status=target_status, then=0),
                        default=1,
                        output_field=IntegerField(),
                    ),
                    'delivery_date', 'created_at' # order them by dates.
                )
                status_label = dict(ProducerOrder.Status.choices).get(target_status, target_status)
                _add_active_tag(active_tags, params, 'sort_by', f'Prioritised: {status_label}')
            else: # Fallback if url was messed with by user.
                sub_orders = sub_orders.order_by('delivery_date', 'created_at')
        else:
            # Default: Oldest to Newest
            sub_orders = sub_orders.order_by('delivery_date', 'created_at')
        
        # Check if user has actively searched anything
        is_filtered = bool(filter_status or start_date or end_date or sort_by != 'date_asc')


        return render(request, "orders/producer_order_list.html", {
            "sub_orders": sub_orders,
            "statuses": ProducerOrder.Status.choices,
            "current_status": filter_status,
            "start_date": start_date,
            "end_date": end_date,
            "sort_by": sort_by,
            "active_tags": active_tags,
            "is_filtered": is_filtered,
        })
    else: # Customer
        producer_id = request.GET.get('producer', '')
        filter_status = request.GET.get('status', '')
        start_date = request.GET.get('start_date', '')
        end_date = request.GET.get('end_date', '')
        query = request.GET.get('q', '').strip()

        params = request.GET.copy()
        active_tags = []

        # fetch producers this specific customer has ordered from
        ordered_producer_ids = ProducerOrder.objects.filter(
            order__customer=user
        ).values_list('producer_id', flat=True).distinct()
        
        User = get_user_model()
        producers = User.objects.filter(
            id__in=ordered_producer_ids
        ).select_related('producer_profile').order_by('email')

        orders = (
            Order.all_objects
            .filter(customer=user)
            .select_related("payment")
            .prefetch_related("sub_orders__producer__producer_profile", "sub_orders__items")
            .order_by("-created_at")
        )

        if producer_id and producer_id.isdigit():
            orders = orders.filter(sub_orders__producer_id=producer_id).distinct()
            
            # Find the producer name for the Active Tag
            matched_producer = next((p for p in producers if str(p.id) == producer_id), None)
            if matched_producer:
                try:
                    p_name = matched_producer.producer_profile.business_name
                except Exception:
                    p_name = matched_producer.email
                _add_active_tag(active_tags, params, 'producer', f'Producer: {p_name}')

        if filter_status and filter_status in Order.Status.values:
            orders = orders.filter(status=filter_status)
            status_label = dict(Order.Status.choices).get(filter_status, filter_status)
            _add_active_tag(active_tags, params, 'status', f'Status: {status_label}')

        if start_date:
            try:
                date.fromisoformat(start_date)
                orders = orders.filter(created_at__date__gte=start_date)
                _add_active_tag(active_tags, params, 'start_date', f'Order date from: {start_date}')
            except ValueError:
                pass

        if end_date:
            try:
                date.fromisoformat(end_date)
                orders = orders.filter(created_at__date__lte=end_date)
                _add_active_tag(active_tags, params, 'end_date', f'Order date to: {end_date}')
            except ValueError:
                pass

        if query:
            orders = orders.filter(order_number__icontains=query)
            _add_active_tag(active_tags, params, 'q', f'Search: {query}')

        paginator = Paginator(orders, 10)
        page_obj = paginator.get_page(request.GET.get("page"))
        page_params = request.GET.copy()
        page_params.pop("page", None)
        base_query = page_params.urlencode()

        return render(request, "orders/customer_order_list.html", {
            "orders": page_obj.object_list,
            "page_obj": page_obj,
            "statuses": Order.Status.choices,
            "current_status": filter_status,
            "producers": producers,
            "current_producer_id": producer_id,
            "start_date": start_date,
            "end_date": end_date,
            "search_query": query,
            "active_tags": active_tags,
            "is_filtered": bool(filter_status or producer_id or start_date or end_date or query),
            "base_query": base_query,
        })


@login_required
def order_detail(request, order_number):
    """
    Detailed view of a single order.
    Accessible by the customer who placed it and any producer with a
    sub-order in it.
    """
    order = get_object_or_404(
        Order.all_objects.select_related("customer", "payment").prefetch_related(
            "sub_orders__producer__producer_profile",
            "sub_orders__items",
        ),
        order_number=order_number,
    )

    is_customer = request.user == order.customer
    # Check if the requesting user is a producer on any sub-order
    user_sub_order = order.sub_orders.filter(producer=request.user).first()
    is_producer_view = user_sub_order is not None

    if not is_customer and not is_producer_view:
        messages.error(request, "You don't have permission to view this order.")
        return redirect("orders:order_list")

    try:
        customer_name = order.customer.customer_profile.full_name
    except AttributeError:
        customer_name = order.customer.email

    commission_rate = getattr(settings, "COMMISSION_RATE", Decimal("0.05"))

    # Build sections — producer sees only their own; customer sees all
    if is_producer_view and not is_customer:
        sub_orders = [user_sub_order]
    else:
        sub_orders = list(order.sub_orders.all())

    producer_sections = []
    for so in sub_orders:
        producer_sections.append({
            "producer_name": get_producer_display_name(so.producer),
            "producer_email": so.producer.email,
            "delivery_date": so.delivery_date,
            "special_instructions": so.special_instructions,
            "items": so.items.all(),
            "subtotal": so.subtotal,
            "commission_amount": so.commission_amount,
            "producer_payment": so.producer_payment,
            "status": so.status,
            "status_display": so.get_status_display(),
        })

    return render(request, "orders/order_detail.html", {
        "order": order,
        "producer_sections": producer_sections,
        "customer_name": customer_name,
        "is_customer": is_customer,
        "is_producer_view": is_producer_view,
        "is_multi_vendor": len(order.sub_orders.all()) > 1,
        "commission_rate_display": f"{int(commission_rate * 100)}%",
        "producer_rate_display": f"{int((1 - commission_rate) * 100)}%",
        "masked_transaction_id": _mask_sensitive_identifier(
            getattr(getattr(order, "payment", None), "transaction_id", "")
        ),
        "masked_payment_method": _format_payment_method_label(
            getattr(getattr(order, "payment", None), "payment_method", "")
        ),
    })


@customer_required
def reorder_order(request, order_number):
    """Re-add items from a historical order to the active cart."""
    if request.method != "POST":
        return redirect("orders:order_detail", order_number=order_number)

    order = get_object_or_404(
        Order.all_objects.prefetch_related("items__product__farm", "items__product__producer"),
        order_number=order_number,
        customer=request.user,
    )

    cart = _get_or_create_active_cart(request.user)

    added_count = 0
    unavailable = []
    adjusted = []
    price_changes = []
    suggestion_product_ids = set()

    for item in order.items.all():
        product = item.product
        if not product:
            unavailable.append(f"{item.product_name} (no longer listed)")
            continue

        ok, reason = _is_product_purchasable(product)
        if not ok:
            suggestion_product_ids.update(
                [p.id for p in _find_alternative_products(product, item.quantity)]
            )
            unavailable.append(f"{item.product_name} ({reason})")
            continue

        if product.farm.is_deleted:
            suggestion_product_ids.update(
                [p.id for p in _find_alternative_products(product, item.quantity)]
            )
            unavailable.append(
                f"{item.product_name} (farm no longer active)"
            )
            continue

        if not product.producer.is_active:
            suggestion_product_ids.update(
                [p.id for p in _find_alternative_products(product, item.quantity)]
            )
            unavailable.append(
                f"{item.product_name} (producer no longer active)"
            )
            continue

        if product.stock_quantity <= 0:
            suggestion_product_ids.update(
                [p.id for p in _find_alternative_products(product, item.quantity)]
            )
            unavailable.append(
                f"{item.product_name} (out of stock)"
            )
            continue

        if item.unit_price != product.price:
            price_changes.append(
                f'{item.product_name}: was £{item.unit_price:.2f}, now £{product.price:.2f}'
            )

        cart_item, _ = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={"quantity": 0},
        )

        remaining_capacity = max(product.stock_quantity - cart_item.quantity, 0)
        if remaining_capacity == 0:
            suggestion_product_ids.update(
                [p.id for p in _find_alternative_products(product, item.quantity)]
            )
            unavailable.append(
                f"{item.product_name} (already at max available quantity)"
            )
            continue

        quantity_to_add = min(item.quantity, remaining_capacity)
        cart_item.quantity += quantity_to_add
        cart_item.save()
        added_count += 1

        if quantity_to_add < item.quantity:
            adjusted.append(
                f"{item.product_name} (added {quantity_to_add} of {item.quantity} requested)"
            )

    if added_count:
        messages.success(request, "Items from your previous order were added to your cart.")
    else:
        messages.warning(request, "No items could be reordered from this order.")

    if adjusted:
        messages.warning(request, "Some items were partially added due to stock changes: " + "; ".join(adjusted))

    if unavailable:
        messages.warning(request, "Some items could not be reordered: " + "; ".join(unavailable))

    if price_changes:
        messages.warning(
            request,
            "Price updates applied during reorder: " + "; ".join(price_changes),
        )

    if suggestion_product_ids:
        _store_alternative_suggestions_in_session(
            request, sorted(suggestion_product_ids),
        )

    return redirect("cart:cart_detail")


@customer_required
def download_receipt(request, order_number):
    """Download a PDF receipt for a historical order."""
    order = get_object_or_404(
        Order.all_objects.select_related("payment").prefetch_related(
            "sub_orders__producer__producer_profile",
            "sub_orders__items",
        ),
        order_number=order_number,
        customer=request.user,
    )

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    def draw_line(text, font="Helvetica", size=10, gap=16):
        nonlocal y
        pdf.setFont(font, size)
        pdf.drawString(50, y, str(text))
        y -= gap

    draw_line("Order Receipt", font="Helvetica-Bold", size=18, gap=22)
    draw_line(f"Order: {order.order_number}")
    draw_line(f"Placed: {order.created_at.strftime('%d %b %Y, %H:%M')}", gap=20)

    draw_line("Delivery", font="Helvetica-Bold", size=12)
    draw_line(order.delivery_address)
    draw_line(order.delivery_postcode, gap=20)

    draw_line("Items", font="Helvetica-Bold", size=12)
    for item in order.items.all():
        line = (
            f"- {item.product_name} | Qty: {item.quantity} | "
            f"Unit: GBP {item.unit_price} | Total: GBP {item.line_total}"
        )
        draw_line(line)
        if y < 100:
            pdf.showPage()
            y = height - 50

    y -= 6
    draw_line(f"Subtotal: GBP {order.subtotal}")
    draw_line(f"Network Commission: GBP {order.commission_amount}")
    draw_line(f"Total Paid: GBP {order.total}", font="Helvetica-Bold", gap=20)

    if getattr(order, "payment", None):
        draw_line("Payment", font="Helvetica-Bold", size=12)
        draw_line(
            f"Method: {_format_payment_method_label(order.payment.payment_method)}"
        )
        draw_line(
            f"Transaction: {_mask_sensitive_identifier(order.payment.transaction_id)}"
        )
        draw_line(f"Status: {order.payment.get_status_display()}")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="receipt-{order.order_number}.pdf"'
    )
    return response


# ---------------------------------------------------------------------------
# REST API for producer dashboard
# ---------------------------------------------------------------------------

class ProducerOrderListAPIView(generics.ListAPIView):
    """
    GET /orders/api/ — returns all sub-orders for the logged-in producer,
    sorted by delivery date.

    Non-producer users receive a 403 Forbidden rather than a misleading
    empty list, making it clear the endpoint is producer-only.
    """
    serializer_class = ProducerSubOrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, "is_producer", False):
            return (
                ProducerOrder.objects
                .filter(producer=user)
                .select_related("order", "order__customer")
                .prefetch_related("items")
                .order_by("delivery_date")
            )
        raise PermissionDenied(
            "Only producer accounts can access this endpoint."
        )


@producer_required
def producer_payouts(request):
    if not getattr(request.user, "is_producer", False):
        messages.error(request, "Only producers can view financial payouts.")
        return redirect("marketplace:product_list")

    valid_statuses =[
        ProducerOrder.Status.CONFIRMED,
        ProducerOrder.Status.DISPATCHED,
        ProducerOrder.Status.DELIVERED
    ]

    sub_orders = ProducerOrder.objects.filter(
        producer=request.user,
        status__in=valid_statuses
    ).select_related('order').order_by('-created_at')

    # Overall totals
    total_sales = sum(so.subtotal for so in sub_orders)
    total_commission = sum(so.commission_amount for so in sub_orders)
    total_payout = sum(so.producer_payment for so in sub_orders)

    # Tax year running total calculation (UK Tax Year starts April 6th)
    today = timezone.localdate()
    if today.month > 4 or (today.month == 4 and today.day >= 6):
        tax_year_start = date(today.year, 4, 6)
    else:
        tax_year_start = date(today.year - 1, 4, 6)

    tax_year_total = sum(
        so.producer_payment for so in sub_orders
        if timezone.localtime(so.created_at).date() >= tax_year_start
    )

    # Group orders by ISO week (Monday to Sunday)
    weeks = defaultdict(list)
    for so in sub_orders:
        local_date = timezone.localtime(so.created_at).date()
        monday = local_date - timedelta(days=local_date.weekday())
        weeks[monday].append(so)

    sorted_weeks = sorted(weeks.items(), key=lambda x: x[0], reverse=True)

    weekly_data = []
    for week_start, orders in sorted_weeks:
        week_end = week_start + timedelta(days=6)

        # Calculate weekly totals
        week_sales = sum(o.subtotal for o in orders)
        week_commission = sum(o.commission_amount for o in orders)
        week_payout = sum(o.producer_payment for o in orders)

        # Add derived Payout Status & Audit Transaction Reference
        for o in orders:
            if o.status == ProducerOrder.Status.DELIVERED:
                o.payout_status = "Processed"
            else:
                o.payout_status = "Pending Bank Transfer"

            try:
                # Assuming Payment is linked via Reverse OnetoOne relation from Order
                o.transaction_id = o.order.payment.transaction_id
            except Exception:
                o.transaction_id = f"REF-{o.order.order_number}"

        weekly_data.append({
            'week_start': week_start,
            'week_end': week_end,
            'orders': orders,
            'sales': week_sales,
            'commission': week_commission,
            'payout': week_payout,
        })

    return render(request, "orders/producer_payouts.html", {
        "weekly_data": weekly_data,
        "tax_year_total": tax_year_total,
        "tax_year_start": tax_year_start,
        "total_sales": total_sales,
        "total_commission": total_commission,
        "total_payout": total_payout,
    })


@producer_required
def producer_payouts_csv(request):
    if not getattr(request.user, "is_producer", False):
        return HttpResponseForbidden("Access Denied")

    # Check if the anonymise toggle was checked
    anonymise = request.GET.get('anonymise', 'false').lower() == 'true'


    valid_statuses =[
        ProducerOrder.Status.CONFIRMED,
        ProducerOrder.Status.DISPATCHED,
        ProducerOrder.Status.DELIVERED
    ]

    # Added prefetch_related('items') to fetch product items without hammering the DB
    sub_orders = ProducerOrder.objects.filter(
        producer=request.user,
        status__in=valid_statuses
    ).select_related(
        'order', 'order__customer', 'order__customer__customer_profile'
    ).prefetch_related('items').order_by('-created_at')

    # Fix Â£ symbol encoding by outputting a UTF-8 BOM
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="producer_financial_report.csv"'
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow([
        'Order Number', 'Order Date', 'Customer', 'Product Items Sold',
        'Delivery Date', 'Order Status', 'Payout Status', 'Transaction Ref',
        'Gross Sales (£)', 'Commission (5%) (£)', 'Your Payout (£)'
    ])

    for so in sub_orders:
        # Check anonymisation parameter
        if anonymise:
            customer_name = "*** Anonymised ***"
        else:
            try:
                customer_name = so.order.customer.customer_profile.full_name
            except AttributeError:
                customer_name = so.order.customer.email

        # Extract item quantity and names
        items_sold = ", ".join([f"{item.quantity}x {item.product_name}" for item in so.items.all()])

        # Payout Status
        payout_status = "Processed" if so.status == ProducerOrder.Status.DELIVERED else "Pending Bank Transfer"

        # Retrieve Transaction ID
        try:
            txn_ref = so.order.payment.transaction_id
        except Exception:
            txn_ref = f"REF-{so.order.order_number}"

        writer.writerow([
            so.order.order_number,
            so.created_at.strftime('%Y-%m-%d'),
            customer_name,
            items_sold,
            so.delivery_date.strftime('%Y-%m-%d'),
            so.get_status_display(),
            payout_status,
            txn_ref,
            so.subtotal,
            so.commission_amount,
            so.producer_payment
        ])

    return response


@producer_required
def producer_payouts_pdf(request):
    #Generates a PDF format of the financial report.
    if not getattr(request.user, "is_producer", False):
        return HttpResponseForbidden("Access Denied")

    anonymise = request.GET.get('anonymise', 'false').lower() == 'true'

    valid_statuses = [
        ProducerOrder.Status.CONFIRMED,
        ProducerOrder.Status.DISPATCHED,
        ProducerOrder.Status.DELIVERED
    ]

    sub_orders = ProducerOrder.objects.filter(
        producer=request.user,
        status__in=valid_statuses
    ).select_related(
        'order', 'order__customer', 'order__customer__customer_profile'
    ).prefetch_related('items').order_by('-created_at')

    producer_name = request.user.producer_profile.business_name if hasattr(request.user, 'producer_profile') else request.user.email

    # Prepare the PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )
    elements = []

    # Get Default Styles
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    title_style.textColor = colors.HexColor("#166534")  #Tailwind green-800
    normal_style = styles['Normal']

    # Title
    elements.append(Paragraph("Financial Payout Report", title_style))
    elements.append(Spacer(1, 10))

    # Meta Info
    status_text = "Anonymised (Privacy Compliant)" if anonymise else "Full Detail"
    gen_date = timezone.localtime(timezone.now()).strftime("%d %b %Y %H:%M")

    meta_info = f"""
    <b>Producer / Business:</b> {producer_name}<br/>
    <b>Report Generated On:</b> {gen_date}<br/>
    <b>Status:</b> {status_text}
    """
    elements.append(Paragraph(meta_info, normal_style))
    elements.append(Spacer(1, 20))

    # Build Table Data
    data = [["Date", "Order #", "Customer", "Status", "Sales", "Comm. (5%)", "Payout"]]

    if not sub_orders:
        data.append(["No completed orders found.", "", "", "", "", "", ""])
    else:
        for so in sub_orders:
            # Handle anonymisation properly
            if anonymise:
                customer_name = "*** Anonymised ***"
            else:
                try:
                    customer_name = so.order.customer.customer_profile.full_name or so.order.customer.email
                except AttributeError:
                    customer_name = so.order.customer.email

            data.append([
                timezone.localtime(so.created_at).strftime("%d %b %Y"),
                str(so.order.order_number),
                customer_name,
                so.get_status_display(),
                f"£{so.subtotal}",
                f"-£{so.commission_amount}",
                f"£{so.producer_payment}"
            ])

    # Calculate column widths to fit A4 (must be total of 535 points wide)
    col_widths =[70, 95, 115, 65, 55, 70, 65]
    table = Table(data, colWidths=col_widths)

    # Base Table Style
    t_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#374151")),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (4, 0), (6, -1), 'RIGHT'),  # Right align numbers
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#dddddd")),
    ])

    # Dynamically style data rows (Commission Red, Payout Green/Bold)
    if sub_orders:
        for i in range(1, len(data)):
            t_style.add('TEXTCOLOR', (5, i), (5, i), colors.HexColor("#dc2626"))  # Danger Red
            t_style.add('TEXTCOLOR', (6, i), (6, i), colors.HexColor("#15803d"))  # Success Green
            t_style.add('FONTNAME', (6, i), (6, i), 'Helvetica-Bold')
    else:
        # Merge columns if no orders are found
        t_style.add('SPAN', (0, 1), (-1, 1))
        t_style.add('ALIGN', (0, 1), (-1, 1), 'CENTER')

    table.setStyle(t_style)
    elements.append(table)

    # Build PDF Document
    doc.build(elements)

    # Get the value from the BytesIO buffer and close it
    pdf = buffer.getvalue()
    buffer.close()

    # Return as an HTTP Response
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="producer_financial_report.pdf"'
    response.write(pdf)

    return response
@login_required
def notifications_list(request):
    """
    Displays all notifications for the user.
    Automatically marks unread notifications as read upon viewing.
    """
    notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    unread_notifications = notifications.filter(is_read=False)
    if unread_notifications:
        unread_notifications.update(is_read=True)

    return render(request, 'orders/notifications.html', {
        'notifications': notifications
    })

# ---------------------------------------------------------------------------
# Admin Commissions (TC-025)
# ---------------------------------------------------------------------------

@admin_required
def admin_commissions(request):
    period = request.GET.get("period")
    producer_id = request.GET.get("producer_id")
    payment_status = request.GET.get("payment_status")
    valid_producer_id = int(producer_id) if producer_id and producer_id.isdigit() else None

    # Base queryset: only non-deleted orders that are delivered
    qs = Order.objects.filter(is_deleted=False, status=Order.Status.DELIVERED)

    # Apply period filter (mirroring TC-025 "Previous 2 weeks", "Current month", "YTD")
    today = timezone.localdate()
    if period == "last_14_days":
        qs = qs.filter(created_at__date__gte=today - timedelta(days=14))
    elif period == "current_month":
        qs = qs.filter(created_at__year=today.year, created_at__month=today.month)
    elif period == "ytd":
        qs = qs.filter(created_at__year=today.year)

    # Apply producer filter if valid
    if valid_producer_id:
        qs = qs.filter(sub_orders__producer_id=valid_producer_id).distinct()

    # Apply payment status
    if payment_status:
        qs = qs.filter(payment__status=payment_status)

    # N+1 Prevention
    qs = qs.select_related("customer", "payment").prefetch_related("sub_orders__producer")
    qs = qs.order_by("-created_at")

    # Calculate summary metrics (Service Layer)
    metrics = aggregate_financial_metrics(qs, producer_id=valid_producer_id)

    # Pagination
    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    for report_order in page_obj.object_list:
        all_sub_orders = list(report_order.sub_orders.all())
        if valid_producer_id:
            display_sub_orders = [
                sub_order for sub_order in all_sub_orders if sub_order.producer_id == valid_producer_id
            ]
        else:
            display_sub_orders = all_sub_orders

        for sub_order in display_sub_orders:
            sub_order.producer_display_name = get_producer_display_name(sub_order.producer)

        report_order.display_sub_orders = display_sub_orders
        report_order.display_producer_payment = sum(
            (sub_order.producer_payment for sub_order in display_sub_orders),
            Decimal("0.00"),
        )

    # Get producers for filter dropdown
    producers = User.objects.filter(role="PRODUCER").order_by("email")

    anonymise = request.GET.get("anonymise") == "1"

    context = {
        "page_obj": page_obj,
        "metrics": metrics,
        "producers": producers,
        "payment_statuses": Payment.Status.choices,
        "current_period": period,
        "current_producer_id": valid_producer_id or "",
        "current_payment_status": payment_status,
        "anonymise": getattr(request, 'GET', {}).get('anonymise') == '1'
    }
    return render(request, "orders/admin_commissions.html", context)


@admin_required
def admin_commissions_detail(request, order_number):
    order = get_object_or_404(
        Order.objects.select_related("customer", "payment").prefetch_related("sub_orders__producer"),
        order_number=order_number,
        is_deleted=False,
        status=Order.Status.DELIVERED
    )
    for sub_order in order.sub_orders.all():
        sub_order.producer_display_name = get_producer_display_name(sub_order.producer)
    return render(request, "orders/admin_commissions_detail.html", {"order": order})


@admin_required
def admin_commissions_csv(request):
    period = request.GET.get("period")
    producer_id = request.GET.get("producer_id")
    payment_status = request.GET.get("payment_status")
    valid_producer_id = int(producer_id) if producer_id and producer_id.isdigit() else None

    qs = Order.objects.filter(is_deleted=False, status=Order.Status.DELIVERED)

    today = timezone.localdate()
    if period == "last_14_days":
        qs = qs.filter(created_at__date__gte=today - timedelta(days=14))
    elif period == "current_month":
        qs = qs.filter(created_at__year=today.year, created_at__month=today.month)
    elif period == "ytd":
        qs = qs.filter(created_at__year=today.year)

    if valid_producer_id:
        qs = qs.filter(sub_orders__producer_id=valid_producer_id).distinct()
    
    if payment_status:
        qs = qs.filter(payment__status=payment_status)

    qs = qs.select_related("customer", "payment").prefetch_related("sub_orders__producer")
    qs = qs.order_by("-created_at")

    applied_filters = {}
    if period:
        applied_filters["period"] = period
    if valid_producer_id:
        applied_filters["producer_id"] = str(valid_producer_id)
    if payment_status:
        applied_filters["payment_status"] = payment_status

    anonymise_raw = (request.GET.get("anonymise") or "").strip().lower()
    anonymise = anonymise_raw in {"1", "true", "yes", "on"}
    if anonymise:
        applied_filters["anonymise"] = "true"

    return generate_commission_csv(
        qs,
        applied_filters=applied_filters or None,
        producer_id=valid_producer_id,
        anonymise=anonymise,
    )


@admin_required
def admin_commissions_accounting_csv(request):
    period = request.GET.get("period")
    producer_id = request.GET.get("producer_id")
    payment_status = request.GET.get("payment_status")
    valid_producer_id = int(producer_id) if producer_id and producer_id.isdigit() else None
    include_pending_raw = (request.GET.get("include_pending") or "").strip().lower()
    include_pending = include_pending_raw in {"1", "true", "yes", "on"}
    
    anonymise_raw = (request.GET.get("anonymise") or "").strip().lower()
    anonymise = anonymise_raw in {"1", "true", "yes", "on"}

    qs = Order.objects.filter(is_deleted=False, status=Order.Status.DELIVERED)

    today = timezone.localdate()
    if period == "last_14_days":
        qs = qs.filter(created_at__date__gte=today - timedelta(days=14))
    elif period == "current_month":
        qs = qs.filter(created_at__year=today.year, created_at__month=today.month)
    elif period == "ytd":
        qs = qs.filter(created_at__year=today.year)

    if valid_producer_id:
        qs = qs.filter(sub_orders__producer_id=valid_producer_id).distinct()

    if payment_status:
        qs = qs.filter(payment__status=payment_status)

    qs = qs.select_related("customer", "payment").prefetch_related("sub_orders__producer")
    qs = qs.order_by("-created_at")

    return generate_commission_accounting_csv(
        qs,
        producer_id=valid_producer_id,
        include_pending=include_pending,
        anonymise=anonymise,
    )

