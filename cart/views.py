from django.shortcuts import render
from decimal import Decimal


def cart_detail(request):
    """
    Renders the cart detail page with mock data grouped by producer.

    --- HANDOFF NOTES FOR BACKEND DEVELOPER ---

    TICKET #59 – Cart State Management (Store Cart ID/Items):
        Replace the mock `cart_items_by_producer` dictionary below with a real
        database query once Cart/CartItem models exist. Retrieve the cart via
        the session.

    TICKET #4 – Create Cart API:
        Once the API endpoints exist (e.g. PATCH /api/cart/items/<id>/,
        DELETE /api/cart/items/<id>/), the +/− and remove buttons in the
        template (data-action attributes) need a small JS file wired up to
        call those endpoints and refresh the totals in the DOM.
        See cart_detail.html for the exact data-action hooks :)

    TICKET #115 – Cart Validation & Error Handling:
        Add server-side guards here: handle a missing/expired cart gracefully,
        reject qty < 1, and return meaningful errors if an item is no longer
        available. The quantity input in the template already enforces min="1"
        on the client side, but server-side validation is still required.

    TICKET #116 – Update Global Cart Counter in Nav Bar:
        `total_items` is already calculated below and passed in context.
        Once the base template nav bar reads {{ total_items }} (or fetches it
        from session), this view already provides the value. After any
        update (ticket #4), the JS should also refresh the nav counter.
    """

    # --- TICKET #59: Mock Data — replace this entire block with a real DB query ---
    # Query Cart → CartItem → Product, group by product.producer (or seller).
    # Each item dict must include: name, unit_price, quantity, image_url, item_total.
    # item_total should ideally be computed here (unit_price * quantity) so the
    # template stays logic-free.
    cart_items_by_producer = {
        "Bristol Valley Farm": [
            {
                "name": "Organic Carrots (1kg)",
                "unit_price": Decimal("2.99"),
                "quantity": 2,
                "image_url": "https://placehold.co/120x120?text=Carrots",
                "item_total": Decimal("5.98"),
            },
            {
                "name": "Free-Range Eggs (dozen)",
                "unit_price": Decimal("4.50"),
                "quantity": 1,
                "image_url": "https://placehold.co/120x120?text=Eggs",
                "item_total": Decimal("4.50"),
            },
        ],
        "East Street Bakery": [
            {
                "name": "Sourdough Loaf",
                "unit_price": Decimal("3.75"),
                "quantity": 1,
                "image_url": "https://placehold.co/120x120?text=Bread",
                "item_total": Decimal("3.75"),
            },
            {
                "name": "Cinnamon Rolls (pack of 4)",
                "unit_price": Decimal("5.00"),
                "quantity": 2,
                "image_url": "https://placehold.co/120x120?text=Rolls",
                "item_total": Decimal("10.00"),
            },
        ],
    }

    # Calculate totals
    subtotal = sum(
        item["item_total"]
        for items in cart_items_by_producer.values()
        for item in items
    )
    # TICKET #60 – Create Totals Dynamically:
    # commission_rate should come from Django settings (e.g. settings.COMMISSION_RATE)
    # or a SiteConfig model, not be hardcoded. The template displays commission_rate_display
    # as a human-readable string,  update that context key too if the rate changes.
    commission_rate = Decimal("0.05")  # TODO: move to settings.COMMISSION_RATE or whatever lol
    commission = (subtotal * commission_rate).quantize(Decimal("0.01"))
    grand_total = subtotal + commission

    # TICKET #116 – Update Global Cart Counter in Nav Bar:
    total_items = sum(
        item["quantity"]
        for items in cart_items_by_producer.values()
        for item in items
    )

    # Per-producer subtotals for the order summary panel
    producer_subtotals = {
        producer: sum(item["item_total"] for item in items)
        for producer, items in cart_items_by_producer.items()
    }

    context = {
        "cart_items_by_producer": cart_items_by_producer,
        "producer_subtotals": producer_subtotals,
        "subtotal": subtotal,
        "commission_rate_display": "5%",
        "commission": commission,
        "grand_total": grand_total,
        "total_items": total_items,
    }

    return render(request, "cart/cart_detail.html", context)
