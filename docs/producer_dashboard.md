# Producer Product Dashboard

**Test Case**: TC-003 Product Listing CRUD

## Overview

The Producer Product Dashboard gives authenticated producers a single view of
all their product listings both available (active) and unavailable (inactive).
It sits behind the `@producer_required` decorator so only producer accounts can
access it.

The dashboard resolves the previously broken `producer_dashboard` redirect that
`producer_register` relied on.

## URL

| Method | Path                            | Name                 |
| ------ | ------------------------------- | -------------------- |
| GET    | `/accounts/producer/dashboard/` | `producer_dashboard` |

## View

`accounts.views.producer_dashboard`

- Queries `Product.objects.filter(producer=request.user)` — no season or
  availability filter, so **all** of the producer's listings appear.
- Passes summary counts to the template: total, active, inactive, out of stock.
- Ordered by most recently updated first (`-updated_at`).

## Template

`accounts/Templates/accounts/producer_dashboard.html`

Extends `base.html`. Renders:

1. **Header** with page title and "Add Product" button.
2. **Summary stats** — four cards showing total / active / inactive / out of
   stock counts.
3. **Product table** with columns: image, name (and farm), category, price/unit,
   stock, season window, status badge, and action buttons.
4. **Empty state** when the producer has no products yet.

### Action buttons per row

| Action                | Method | URL name                     | Behaviour                         |
| --------------------- | ------ | ---------------------------- | --------------------------------- |
| Edit                  | GET    | `marketplace:product_edit`   | Opens the product form pre-filled |
| Activate / Deactivate | POST   | `marketplace:product_toggle` | Flips `is_available`              |
| Delete                | POST   | `marketplace:product_delete` | Soft-deletes the product          |

## Supporting Views (marketplace app)

### product_edit

`marketplace.views.product_edit(request, pk)`

| Method     | Path                          | Name                       |
| ---------- | ----------------------------- | -------------------------- |
| GET / POST | `/marketplace/edit/<int:pk>/` | `marketplace:product_edit` |

- Reuses `ProductAddForm` with `instance=product`.
- Enforces ownership via `get_object_or_404(Product, pk=pk, producer=request.user)`.
- Shares `product_form.html` with the add flow; passes `editing=True` so the
  template renders "Edit Product" / "Save Changes" instead of "Add Produce" /
  "Create Listing".
- Redirects to `producer_dashboard` on success.

### product_toggle

`marketplace.views.product_toggle(request, pk)`

| Method | Path                            | Name                         |
| ------ | ------------------------------- | ---------------------------- |
| POST   | `/marketplace/toggle/<int:pk>/` | `marketplace:product_toggle` |

- POST-only (`@require_POST`) to prevent accidental toggling.
- Flips the `is_available` boolean and saves.

### product_delete

`marketplace.views.product_delete(request, pk)`

| Method | Path                            | Name                         |
| ------ | ------------------------------- | ---------------------------- |
| POST   | `/marketplace/delete/<int:pk>/` | `marketplace:product_delete` |

- POST-only with a client-side confirmation prompt.
- Calls `product.delete()` which triggers `SoftDeleteModel` — the record is
  retained for audit but hidden from normal queries.

## Navigation

A "My Products" link is added to both the desktop and mobile navigation menus
in `base.html`, visible only to authenticated producers
(`{% if request.user.is_producer %}`).
