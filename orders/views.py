from collections import OrderedDict, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Case, When, IntegerField
from django.db.models.functions import Greatest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.template.loader import get_template

import stripe
import csv
from xhtml2pdf import pisa

from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from accounts.decorators import customer_required, producer_required
from cart.models import Cart, CartItem
from cart.views import _get_or_create_active_cart, _validate_cart_items
from products.models import Product

from .forms import CheckoutForm, ProducerDeliveryForm
from .models import (
    Notification, Order, OrderItem, Payment, ProducerOrder,
    get_producer_display_name,
)
from .serializers import ProducerSubOrderSerializer


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
                        insufficient.append(
                            f'"{ci.product.name}" only has {current} in stock '
                            f'(you requested {ci.quantity}).'
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
                    special_instructions=checkout_form.cleaned_data.get("special_instructions", ""),
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

                        # Atomically decrease stock using an F-expression so
                        # concurrent requests can't read stale values.  Greatest()
                        # clamps the result to zero to prevent negative stock.
                        Product.objects.filter(pk=ci.product_id).update(
                            stock_quantity=Greatest(
                                F("stock_quantity") - ci.quantity, 0
                            )
                        )

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
    else:
        orders = (
            Order.objects
            .filter(customer=user)
            .prefetch_related("sub_orders__producer__producer_profile")
            .order_by("-created_at")
        )
        return render(request, "orders/customer_order_list.html", {
            "orders": orders,
        })


@login_required
def order_detail(request, order_number):
    """
    Detailed view of a single order.
    Accessible by the customer who placed it and any producer with a
    sub-order in it.
    """
    order = get_object_or_404(
        Order.objects.select_related("customer", "payment").prefetch_related(
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
        "is_producer_view": is_producer_view,
        "is_multi_vendor": len(order.sub_orders.all()) > 1,
        "commission_rate_display": f"{int(commission_rate * 100)}%",
        "producer_rate_display": f"{int((1 - commission_rate) * 100)}%",
    })


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

    # Prepare Context for the PDF HTML Template
    template_path = 'orders/pdf_payout_report.html'
    context = {
        'sub_orders': sub_orders,
        'anonymise': anonymise,
        'producer_name': request.user.producer_profile.business_name if hasattr(request.user,
                                                                                'producer_profile') else request.user.email,
    }

    # Render HTML and convert to PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="producer_financial_report.pdf"'

    template = get_template(template_path)
    html = template.render(context)

    # Create the PDF
    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse('We had some errors generating the PDF.')

    return response
