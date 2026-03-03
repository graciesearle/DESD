# Cart Feature Documentation

## Overview

The cart feature allows logged-in customers to add products to a shopping cart, modify quantities, and view a grouped breakdown by producer before proceeding to checkout. The cart is persisted server-side (PostgreSQL) and validated against live product state on every access.

---

## Feature Summary

| Capability | Description |
|---|---|
| **Add to Cart** | From the marketplace, click "Add to Cart" on any product card |
| **View Cart** | Navigate to `/cart/` to see all items grouped by producer |
| **Update Quantity** | Click +/− or type a quantity directly on the cart page |
| **Remove Item** | Click the bin icon next to any item |
| **Nav Counter** | A badge on the cart icon (in both navbars) shows the total item count |
| **Lazy Validation** | Stale items are auto-cleaned with user-facing warnings on every cart page load |
| **Commission** | A configurable commission rate (default 5%) is applied on top of the subtotal |

---

## Architecture

### Files

| File | Role |
|---|---|
| `cart/models.py` | `Cart` and `CartItem` Django models |
| `cart/views.py` | Cart detail view + 3 JSON API endpoints |
| `cart/urls.py` | URL routing for the page + API |
| `cart/context_processors.py` | Injects `cart_item_count` into all templates |
| `cart/static/cart/js/cart.js` | AJAX interactions on the cart detail page |
| `cart/templates/cart/cart_detail.html` | Cart page template |
| `cart/tests.py` | 24 unit tests |
| `cart/admin.py` | Django admin registration |

### Data Flow

```
[Marketplace Page]                    [Cart Detail Page]
       │                                     │
       │ POST /cart/api/add/                  │ PATCH /cart/api/update/<id>/
       │ (Add to Cart button)                 │ DELETE /cart/api/remove/<id>/
       ▼                                     ▼
  ┌──────────────────────────────────────────────┐
  │              cart/views.py                    │
  │                                              │
  │  1. Validate product (stock, season, etc.)   │
  │  2. Create/update CartItem                   │
  │  3. Return JSON response                     │
  └──────────────────────────────────────────────┘
                       │
                       ▼
             ┌──────────────────┐
             │  PostgreSQL DB   │
             │  Cart + CartItem │
             └──────────────────┘
```

---

## API Reference

All endpoints require authentication (`@login_required`). Unauthenticated requests receive a `302` redirect to the login page.

### POST `/cart/api/add/`

Adds a product to the user's active cart. If the product is already in the cart, the quantity is incremented.

**Request body:**
```json
{
    "product_id": 42,
    "quantity": 1
}
```

**Success response (200):**
```json
{
    "success": true,
    "item_id": 7,
    "quantity": 3,
    "item_total": "8.97",
    "cart_total_items": 5,
    "grand_total": "15.75"
}
```

**Error response (400):**
```json
{
    "error": "Cannot add 5. Only 3 \"Organic Carrots\" in stock (2 already in your cart)."
}
```

### PATCH `/cart/api/update/<item_id>/`

Sets the quantity of an existing cart item.

**Request body:**
```json
{
    "quantity": 4
}
```

**Success response (200):**
```json
{
    "success": true,
    "item_id": 7,
    "quantity": 4,
    "item_total": "11.96",
    "cart_total_items": 6,
    "subtotal": "20.46",
    "commission": "1.02",
    "grand_total": "21.48",
    "producer_subtotals": {
        "Bristol Valley Farm": "11.96",
        "East Street Bakery": "8.50"
    }
}
```

### DELETE `/cart/api/remove/<item_id>/`

Removes an item from the cart entirely.

**Success response (200):**
```json
{
    "success": true,
    "cart_total_items": 2,
    "subtotal": "8.50",
    "commission": "0.43",
    "grand_total": "8.93",
    "producer_subtotals": {
        "East Street Bakery": "8.50"
    }
}
```

---

## Validation Rules

All validation runs server-side in `cart/views.py`. Client-side validation (e.g., `min="1"`, `max` on the quantity input) is a UX convenience only and is **not** trusted.

### On Add / Update

| Check | Condition | Error |
|---|---|---|
| Product exists | Product ID is valid | 404 |
| Not soft-deleted | `is_deleted = False` | 400: "no longer listed" |
| Available | `is_available = True` | 400: "currently unavailable" |
| In season | `season_start ≤ today ≤ season_end` | 400: "not in season" / "no longer in season" |
| Stock limit | `requested_qty ≤ stock_quantity` | 400: "Only N in stock" |
| Minimum quantity | `quantity ≥ 1` | 400: "at least 1" |

### On Cart Page Load (Lazy Validation)

Every time `/cart/` is loaded, each `CartItem` is re-validated against the current product state. This handles edge cases where product data changed *after* the item was added:

| Scenario | Action | User sees |
|---|---|---|
| Product soft-deleted | Item removed | ⚠️ "X is no longer listed and was removed from your cart." |
| Product unavailable | Item removed | ⚠️ "X is currently unavailable and was removed..." |
| Product out of season | Item removed | ⚠️ "X is no longer in season and was removed..." |
| Farm deleted | Item removed | ⚠️ "X is from a farm that is no longer active..." |
| Producer deactivated | Item removed | ⚠️ "X is from a producer that is no longer active..." |
| Stock < cart qty (stock > 0) | Qty reduced to stock | ⚠️ "X — only N left in stock. Your quantity was reduced from M to N." |
| Stock = 0 | Item removed | ⚠️ "X is now out of stock and was removed..." |

These warnings use Django's `messages` framework and appear as alert banners at the top of the cart page. They are displayed once and auto-clear on the next page load.

---

## Edge Cases & Developer Notes

### Cart Lifecycle & States

The `Cart` model has a `status` field with three possible states. This is necessary because the database strictly enforces **one active cart per user** (via a `UniqueConstraint`).

1. **`active` (The Current Cart)**
   - The cart the user is currently interacting with. All "Add to Cart" requests modify this single active cart.

2. **`ordered` (The Completed Cart)**
   - When a user finishes the checkout process, their `active` cart has its status changed to `ordered`.
   - **How it changes:** This is triggered by the Order/Checkout application (to be implemented). Changing the status to `ordered` frees up the user's "slot". The next time they shop, a fresh `active` cart is generated. The `ordered` cart stays in the database for history/receipt generation.

3. **`abandoned` (The Discarded Cart)**
   - Used when a cart needs to be cleared out without an order being placed.
   - **How it changes:** Currently, only an administrator can mark a cart as `abandoned` via the Django Admin. In the future, a celery task could be written to find `active` carts older than 30 days and mark them as `abandoned`.
   - Like the `ordered` state, this removes the `active` flag, giving the user a fresh cart next time they shop, while preserving the data for business analysis (e.g., "most abandoned products").

### No Price Snapshots

- `CartItem` does not store a price copy. `item_total` is computed from live `Product.price × quantity`.
- **Implication:** If a producer changes a product's price, the cart total changes too. This is intentional, it avoids stale-price bugs and keeps the cart always accurate.
- Price locking should be implemented at the **order/checkout** stage, not in the cart.

### CSRF for AJAX

- `CSRF_COOKIE_HTTPONLY = True` means JavaScript cannot read the CSRF cookie directly.
- The CSRF token is embedded via `<meta name="csrf-token" content="{{ csrf_token }}">` in the base template.
- JavaScript reads this meta tag and includes it in the `X-CSRFToken` header on every `fetch()` call.
- This is Django's recommended approach. Same-origin policy prevents cross-site scripts from reading the meta tag.

### Commission Rate

- Stored in `settings.CART_COMMISSION_RATE` (default: `Decimal('0.05')` → 5%).
- To change: edit `CART_COMMISSION_RATE` in `core/settings.py`.
- The display string (e.g., "5%") is derived automatically in `cart/views.py`.

### Nav Counter (Context Processor)

- `cart.context_processors.cart_item_count` is registered in `TEMPLATES → OPTIONS → context_processors` in settings.
- It injects `{{ cart_item_count }}` into every template context.
- For unauthenticated users, the count is `0`.
- The counter shows total **quantity** (not distinct products): if a user has 3× Carrots and 2× Eggs, the counter shows `5`.

### AJAX DOM Updates

- On the cart page, `cart.js` handles all interactions without page reloads.
- Data attributes (`data-item-id`, `data-display`, `data-cart-count`, etc.) are used to target DOM elements.
- After an API call, the JS updates: the quantity input, item total, producer subtotal, subtotal, commission, grand total, and the nav counter.
- If all items in a producer group are removed, the entire producer card is removed from the DOM.
- If the cart becomes empty, the page reloads to show the empty-cart state.

---

## Testing

Run the cart test suite:

```bash
docker compose exec web python manage.py test cart --verbosity=2
```

### Test Coverage (24 tests)

| Category | Tests |
|---|---|
| Model constraints | One active cart per user, unique product per cart, `item_total` property |
| API: Add | Create cart + item, increment existing, over-stock rejected, unavailable rejected, out-of-season rejected, deleted product rejected, anonymous redirect |
| API: Update | Valid update, over-stock rejected, below-one rejected |
| API: Remove | Remove item, cart persists when empty |
| Cart detail view | Items displayed, anonymous redirect, correct totals |
| Lazy validation | Out-of-season removal + message, unavailable removal + message, qty auto-reduction + message, out-of-stock removal + message |
| Context processor | Correct count for authenticated user, zero for anonymous |

---

## URLs

| URL | Method | Description |
|---|---|---|
| `/cart/` | GET | Cart detail page (with lazy validation) |
| `/cart/api/add/` | POST | Add item to cart |
| `/cart/api/update/<item_id>/` | PATCH | Update item quantity |
| `/cart/api/remove/<item_id>/` | DELETE | Remove item from cart |
