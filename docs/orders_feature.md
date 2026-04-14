# Orders Feature Documentation

## What this covers

This document explains how ordering works now that checkout supports **multiple producers in one order**.

If you only need the data model details, jump to [docs/models/orders_model.md](docs/models/orders_model.md).

---

## Quick overview

A customer can put items from several producers into one cart, check out once, and get one order number.

Under the hood:

- One `Order` is created for the customer
- One `ProducerOrder` is created per producer involved
- Each purchased line item (for example, "Organic Carrots × 3") is saved as an `OrderItem` and linked to both the parent `Order` and the relevant `ProducerOrder`
- One test-mode `Payment` is recorded against the parent `Order`
- Notifications are sent to each producer and to the customer

So the customer gets one tidy order to track, while each producer only sees and handles their own slice.

### Quick term examples

- **Line item**: One product row with quantity, for example `Organic Carrots × 3`.
- **Sub-order (`ProducerOrder`)**: One producer's part of the basket, for example all Bristol Valley Farm items.
- **Parent order (`Order`)**: The single customer order that groups all sub-orders under one order number.

---

## Checkout behaviour (customer view)

### 1) Cart grouping

The checkout page groups products by producer so the customer can clearly see:

- Which items belong to which producer
- Each producer subtotal
- Each producer's minimum lead time

### 2) Delivery details

There are two kinds of delivery fields:

- **Shared** fields once per checkout: delivery address + postcode
- **Per-producer** field: delivery date

This means a customer can choose different delivery dates for different producers in the same transaction.

### 3) Validation

On submit:

- Shared checkout form must be valid
- Every producer delivery form must be valid
- Each producer date must respect that producer's `lead_time_hours`

If any producer section fails, checkout re-renders with clear inline errors.

### 4) Financials shown to customer

The summary shows:

- Order subtotal
- Network commission
- Total paid

Commission is included in the total and split internally.

---

## Checkout behaviour (system flow)

All order creation runs in a single database transaction.

### Stock safety

Before creating records, the flow locks product rows with `select_for_update()` and checks stock again.

Why we do this:

- Cart validation can pass
- Another checkout can complete a second later
- Stock can change between page render and submit

If stock is no longer sufficient, no order is created and the customer gets a useful error.

When order items are written, stock is decremented atomically with an `F()` expression.

### Record creation order

1. Create parent `Order`
2. For each producer:
   - Create `ProducerOrder`
   - Create linked `OrderItem` rows
   - Calculate and save producer-level financials
   - Send producer notification
3. Recalculate and save parent `Order` totals
4. Create `Payment` (test mode)
5. Mark cart as `ordered`
6. Send customer confirmation notification

If anything fails in the transaction, nothing is partially saved.

---

## Financial rules

Current commission model:

- `commission_rate` defaults to `0.05` (5%)
- Customer `total == subtotal` (commission is not added on top)
- Each producer receives `subtotal - commission` for their own `ProducerOrder`
- Parent `Order` totals are aggregate sums from all child `ProducerOrder` rows

Rounding:

- Commission and producer payment are rounded to 2 decimal places
- Parent totals are built from rounded producer splits

---

## Permissions and visibility

### Customer

- Can see their own parent orders
- Can open a single order view with all producer sections

### Producer

- Can see only their own `ProducerOrder` rows in list/API views
- In a shared order detail page, sees only their own section and items

### API access

`GET /orders/api/` is producer-only.

- Producer account: gets their sub-orders
- Non-producer authenticated account: `403`
- Anonymous user: blocked by authentication

---

## Templates and pages

### Customer-facing

- `orders/templates/orders/checkout.html`
- `orders/templates/orders/order_confirmation.html`
- `orders/templates/orders/customer_order_list.html`
- `orders/templates/orders/order_detail.html`

### Producer-facing

- `orders/templates/orders/producer_order_list.html`
- Producer slice inside `orders/templates/orders/order_detail.html`

---

## Common questions

### Why not store producer directly on `Order`?

Because one order can now include several producers. Producer-specific data lives on `ProducerOrder`.

### Why keep both `OrderItem.order` and `OrderItem.producer_order`?

It makes both views straightforward:

- Customer history/reporting from the parent `Order`
- Producer fulfilment from their own `ProducerOrder`

---

## Test coverage

`orders/tests.py` includes coverage for:

- Single-producer checkout regression
- Multi-producer checkout flow (`TC-008`)
- Per-producer lead-time enforcement
- Producer-only visibility in order detail
- Stock safety behaviour at checkout
- Commission calculations (`TC-025`)
- Producer API auth and response behaviour

Run:

```bash
docker exec desd-web-1 python manage.py test orders --verbosity=2
```
