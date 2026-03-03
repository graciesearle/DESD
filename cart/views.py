import json
from collections import OrderedDict
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from products.models import Product
from .models import Cart, CartItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_active_cart(user):
    """Return the user's single active cart, creating one if needed."""
    cart, _created = Cart.objects.get_or_create(user=user, status='active')
    return cart


def _is_product_purchasable(product):
    """
    Check that a product can currently be added to a cart.
    Returns (ok: bool, reason: str | None).
    """
    if product.is_deleted:
        return False, f'"{product.name}" is no longer listed.'
    if not product.is_available:
        return False, f'"{product.name}" is currently unavailable.'

    today = timezone.now().date()
    if product.season_start and product.season_start > today:
        return False, f'"{product.name}" is not yet in season.'
    if product.season_end and product.season_end < today:
        return False, f'"{product.name}" is no longer in season.'

    return True, None


def _validate_cart_items(request, cart):
    """
    Lazy validation – run on every cart page load.
    Removes or adjusts items that are no longer valid and adds Django
    messages so the user knows what changed.
    """
    items = cart.items.select_related(
        'product', 'product__producer', 'product__farm',
    )
    for item in items:
        product = item.product

        # 1. Product still purchasable?
        ok, reason = _is_product_purchasable(product)
        if not ok:
            messages.warning(request, f'{reason} It was removed from your cart.')
            item.delete()
            continue

        # 2. Farm still active?
        if product.farm.is_deleted:
            messages.warning(
                request,
                f'"{product.name}" is from a farm that is no longer active '
                f'and was removed from your cart.',
            )
            item.delete()
            continue

        # 3. Producer still active?
        if not product.producer.is_active:
            messages.warning(
                request,
                f'"{product.name}" is from a producer that is no longer active '
                f'and was removed from your cart.',
            )
            item.delete()
            continue

        # 4. Quantity exceeds current stock?
        if item.quantity > product.stock_quantity:
            if product.stock_quantity == 0:
                messages.warning(
                    request,
                    f'"{product.name}" is now out of stock and was removed '
                    f'from your cart.',
                )
                item.delete()
            else:
                old_qty = item.quantity
                item.quantity = product.stock_quantity
                item.save()
                messages.warning(
                    request,
                    f'"{product.name}" — only {product.stock_quantity} left in '
                    f'stock. Your quantity was reduced from {old_qty} to '
                    f'{product.stock_quantity}.',
                )


def _cart_summary(cart):
    """
    Build the grouped-by-producer data structure and totals that both the
    template view and the JSON API can use.
    """
    items = (
        cart.items
        .select_related('product', 'product__producer', 'product__farm', 'product__category')
        .order_by('product__producer__email', 'added_at')
    )

    cart_items_by_producer = OrderedDict()
    for item in items:
        # Use producer profile business_name if available, else email
        producer = item.product.producer
        try:
            producer_name = producer.producer_profile.business_name
        except Exception:
            producer_name = producer.email

        cart_items_by_producer.setdefault(producer_name, []).append({
            'id': item.id,
            'product_id': item.product.id,
            'name': item.product.name,
            'unit_price': item.product.price,
            'quantity': item.quantity,
            'image_url': item.product.image.url if item.product.image else 'https://placehold.co/120x120?text=No+Image',
            'item_total': item.item_total,
            'unit': item.product.unit,
            'stock_quantity': item.product.stock_quantity,
        })

    grand_total = sum(
        i['item_total']
        for items_list in cart_items_by_producer.values()
        for i in items_list
    )

    total_items = sum(
        i['quantity']
        for items_list in cart_items_by_producer.values()
        for i in items_list
    )

    producer_subtotals = {
        producer: sum(i['item_total'] for i in items_list)
        for producer, items_list in cart_items_by_producer.items()
    }

    return {
        'cart_items_by_producer': cart_items_by_producer,
        'producer_subtotals': producer_subtotals,
        'grand_total': grand_total,
        'total_items': total_items,
    }


# ---------------------------------------------------------------------------
# Page view
# ---------------------------------------------------------------------------

@login_required
def cart_detail(request):
    """
    Renders the cart detail page with real data.
    Runs lazy validation on every load to clean stale items.
    """
    cart = _get_or_create_active_cart(request.user)

    # Lazy validation — clean up stale / invalid items
    _validate_cart_items(request, cart)

    # Refresh the cart queryset after validation may have deleted items
    cart.refresh_from_db()

    context = _cart_summary(cart)
    return render(request, 'cart/cart_detail.html', context)


# ---------------------------------------------------------------------------
# Cart API (JSON endpoints)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def api_add_item(request):
    """
    POST /cart/api/add/
    Body JSON: { "product_id": int, "quantity": int (optional, default 1) }
    """
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    product_id = body.get('product_id')
    quantity = body.get('quantity', 1)

    if not product_id:
        return JsonResponse({'error': 'product_id is required.'}, status=400)

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'quantity must be an integer.'}, status=400)

    if quantity < 1:
        return JsonResponse({'error': 'Quantity must be at least 1.'}, status=400)

    # Fetch product (including soft-deleted via all_objects so we can give a
    # proper error message rather than a 404).
    try:
        product = Product.all_objects.select_related('farm').get(pk=product_id)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found.'}, status=404)

    # Purchasability checks
    ok, reason = _is_product_purchasable(product)
    if not ok:
        return JsonResponse({'error': reason}, status=400)

    # Stock check
    cart = _get_or_create_active_cart(request.user)
    existing_item = cart.items.filter(product=product).first()
    new_qty = (existing_item.quantity if existing_item else 0) + quantity

    if new_qty > product.stock_quantity:
        return JsonResponse({
            'error': (
                f'Cannot add {quantity}. Only {product.stock_quantity} '
                f'"{product.name}" in stock'
                f'{f" ({existing_item.quantity} already in your cart)" if existing_item else ""}.'
            ),
        }, status=400)

    # Create or increment
    if existing_item:
        existing_item.quantity = new_qty
        existing_item.save()
        item = existing_item
    else:
        item = CartItem.objects.create(
            cart=cart, product=product, quantity=quantity,
        )

    # Return updated cart summary
    summary = _cart_summary(cart)
    return JsonResponse({
        'success': True,
        'item_id': item.id,
        'quantity': item.quantity,
        'item_total': str(item.item_total),
        'cart_total_items': summary['total_items'],
        'grand_total': str(summary['grand_total']),
    })


@login_required
@require_http_methods(['PATCH'])
def api_update_item(request, item_id):
    """
    PATCH /cart/api/update/<item_id>/
    Body JSON: { "quantity": int }
    """
    cart = _get_or_create_active_cart(request.user)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    quantity = body.get('quantity')
    if quantity is None:
        return JsonResponse({'error': 'quantity is required.'}, status=400)

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'quantity must be an integer.'}, status=400)

    if quantity < 1:
        return JsonResponse({'error': 'Quantity must be at least 1.'}, status=400)

    if quantity > item.product.stock_quantity:
        return JsonResponse({
            'error': (
                f'Only {item.product.stock_quantity} "{item.product.name}" '
                f'in stock.'
            ),
        }, status=400)

    item.quantity = quantity
    item.save()

    summary = _cart_summary(cart)
    return JsonResponse({
        'success': True,
        'item_id': item.id,
        'quantity': item.quantity,
        'item_total': str(item.item_total),
        'cart_total_items': summary['total_items'],
        'grand_total': str(summary['grand_total']),
        'producer_subtotals': {k: str(v) for k, v in summary['producer_subtotals'].items()},
    })


@login_required
@require_http_methods(['DELETE'])
def api_remove_item(request, item_id):
    """
    DELETE /cart/api/remove/<item_id>/
    """
    cart = _get_or_create_active_cart(request.user)
    item = get_object_or_404(CartItem, pk=item_id, cart=cart)
    item.delete()

    summary = _cart_summary(cart)
    return JsonResponse({
        'success': True,
        'cart_total_items': summary['total_items'],
        'grand_total': str(summary['grand_total']),
        'producer_subtotals': {k: str(v) for k, v in summary['producer_subtotals'].items()},
    })
