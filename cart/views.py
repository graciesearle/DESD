import json
from collections import OrderedDict
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from products.models import Product
from .models import Cart, CartItem


ALTERNATIVE_SUGGESTIONS_SESSION_KEY = 'cart_alternative_suggestions'
ALTERNATIVE_SUGGESTIONS_TTL_SECONDS = 60 * 15
CART_ALLERGEN_ACK_SESSION_KEY = 'cart_allergen_acknowledged_item_ids'


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

    if product.season_start and product.season_end:
        current_md = timezone.now().strftime("%m-%d")
        
        if product.season_start <= product.season_end:
            in_season = product.season_start <= current_md <= product.season_end
        else:
            in_season = current_md >= product.season_start or current_md <= product.season_end
            
        if not in_season:
            return False, f'"{product.name}" is no longer in season.'

    return True, None


def _find_alternative_products(product, requested_quantity, limit=3):
    """Find in-stock same-name products from different producers."""
    return list(
        Product.objects.active_and_in_season()
        .filter(
            name__iexact=product.name,
            stock_quantity__gt=0,
        )
        .exclude(pk=product.pk)
        .exclude(producer=product.producer)
        .order_by('price', '-stock_quantity')[:limit]
    )


def _build_alternative_cards(products):
    """Serialize product objects for card-style alternative suggestions."""
    cards = []
    for p in products:
        try:
            producer_name = p.producer.producer_profile.business_name
        except Exception:
            producer_name = p.producer.email

        cards.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'price': p.price,
            'unit': p.unit,
            'stock_quantity': p.stock_quantity,
            'producer_name': producer_name,
            'farm_name': p.farm.name if p.farm else '',
            'image_url': p.image.url if p.image else 'https://placehold.co/400x400?text=No+Image',
        })

    return cards


def _store_alternative_suggestions_in_session(request, product_ids):
    """Persist alternative suggestion product IDs with a short-lived TTL."""
    if not product_ids:
        return

    existing = request.session.get(ALTERNATIVE_SUGGESTIONS_SESSION_KEY, {})
    existing_ids = existing.get('product_ids', []) if isinstance(existing, dict) else []

    merged_ids = list(dict.fromkeys(existing_ids + list(product_ids)))
    request.session[ALTERNATIVE_SUGGESTIONS_SESSION_KEY] = {
        'product_ids': merged_ids,
        'expires_at': int(timezone.now().timestamp()) + ALTERNATIVE_SUGGESTIONS_TTL_SECONDS,
    }


def _get_active_alternative_suggestion_ids(request):
    """Return unexpired alternative suggestion IDs from session, else clear."""
    payload = request.session.get(ALTERNATIVE_SUGGESTIONS_SESSION_KEY)
    if not isinstance(payload, dict):
        return []

    expires_at = payload.get('expires_at')
    product_ids = payload.get('product_ids', [])
    now_ts = int(timezone.now().timestamp())

    if not expires_at or expires_at < now_ts:
        request.session.pop(ALTERNATIVE_SUGGESTIONS_SESSION_KEY, None)
        return []

    return product_ids


def _format_alternative_suggestions(product, requested_quantity):
    """Format alternative producer options for customer-facing messages."""
    alternatives = _find_alternative_products(product, requested_quantity)
    if not alternatives:
        return ''

    formatted_options = []
    for alt in alternatives:
        try:
            producer_name = alt.producer.producer_profile.business_name
        except Exception:
            producer_name = alt.producer.email

        formatted_options.append(
            f'{producer_name} (£{alt.price} / {alt.unit}, {alt.stock_quantity} in stock)'
        )

    return f' Alternative options: ' + '; '.join(formatted_options) + '.'


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
                alternatives = _find_alternative_products(product, item.quantity)
                if alternatives:
                    suggestion_ids = getattr(request, '_cart_alternative_product_ids', set())
                    suggestion_ids.update([alt.id for alt in alternatives])
                    request._cart_alternative_product_ids = suggestion_ids

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
        .prefetch_related('product__allergens')
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
            'allergen_names': [a.name for a in item.product.allergens.all()],
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

    session_suggestion_ids = _get_active_alternative_suggestion_ids(request)
    runtime_suggestion_ids = list(getattr(request, '_cart_alternative_product_ids', set()))
    suggestion_ids = list(dict.fromkeys(session_suggestion_ids + runtime_suggestion_ids))

    if runtime_suggestion_ids:
        _store_alternative_suggestions_in_session(request, runtime_suggestion_ids)

    suggested_products = []
    if suggestion_ids:
        product_map = {
            p.id: p
            for p in Product.objects.active_and_in_season()
            .select_related('producer', 'producer__producer_profile', 'farm')
            .filter(pk__in=suggestion_ids)
        }
        for pid in suggestion_ids:
            product = product_map.get(pid)
            if product:
                suggested_products.append(product)

    context = _cart_summary(cart)
    context['alternative_products'] = _build_alternative_cards(suggested_products)
    return render(request, 'cart/cart_detail.html', context)


@login_required
@require_POST
def confirm_allergens_and_checkout(request):
    """Require acknowledgement of allergen info for each cart item before checkout."""
    cart = _get_or_create_active_cart(request.user)
    _validate_cart_items(request, cart)

    cart_items = list(cart.items.select_related('product'))
    if not cart_items:
        messages.warning(request, 'Your cart is empty.')
        return redirect('cart:cart_detail')

    if request.POST.get('ack_allergens') != 'on':
        messages.warning(
            request,
            'Please confirm allergen information before checkout.',
        )
        return redirect('cart:cart_detail')

    request.session[CART_ALLERGEN_ACK_SESSION_KEY] = [item.id for item in cart_items]
    return redirect('orders:checkout')


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
        alternatives_text = _format_alternative_suggestions(product, quantity)
        return JsonResponse({
            'error': (
                f'Cannot add {quantity}. Only {product.stock_quantity} '
                f'"{product.name}" in stock'
                f'{f" ({existing_item.quantity} already in your cart)" if existing_item else ""}.'
                f'{alternatives_text}'
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

    request.session.pop(CART_ALLERGEN_ACK_SESSION_KEY, None)

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
        alternatives_text = _format_alternative_suggestions(item.product, quantity)
        return JsonResponse({
            'error': (
                f'Only {item.product.stock_quantity} "{item.product.name}" '
                f'in stock.{alternatives_text}'
            ),
        }, status=400)

    item.quantity = quantity
    item.save()
    request.session.pop(CART_ALLERGEN_ACK_SESSION_KEY, None)

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
    request.session.pop(CART_ALLERGEN_ACK_SESSION_KEY, None)

    summary = _cart_summary(cart)
    return JsonResponse({
        'success': True,
        'cart_total_items': summary['total_items'],
        'grand_total': str(summary['grand_total']),
        'producer_subtotals': {k: str(v) for k, v in summary['producer_subtotals'].items()},
    })
