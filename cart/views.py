from django.shortcuts import render
from decimal import Decimal


def cart_detail(request):
    """
    Renders the cart detail page, currently using mock data.

    Ticket #59 - Cart State Management: replace the mock ``cart_items_by_producer``
    dict below with a real query once the Cart/CartItem models are built. See the
    inline comment on the mock data for the required shape.

    Ticket #4 - Cart API: the +/- and remove buttons in the template are marked
    with ``data-action`` attributes, ready to be wired to API endpoints.

    Ticket #115 - Validation: server-side guards for expired carts, qty < 1, and
    out-of-stock items should be added here. The template enforces min="1" client-side.

    Ticket #116 - Nav Counter: ``total_items`` is already in context. The nav bar
    template just needs to render it; find some way to keep it in sync.
    """

    # --- Ticket #59: replace this mock dict with a real cart query ---
    # Group CartItems by producer. Each item needs: name, unit_price,
    # quantity, image_url, item_total. Computing item_total in the view
    # keeps the template free of business logic.
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
    # Ticket #60 - commission_rate should not be hardcoded. Consider moving it
    # to Django settings or a config model; update commission_rate_display in
    # the context to match if it changes.
    commission_rate = Decimal("0.05")  # TODO: move to settings or a config model
    commission = (subtotal * commission_rate).quantize(Decimal("0.01"))
    grand_total = subtotal + commission

    # Ticket #116 - total_items is passed to the template for the nav bar counter.
    # (ticket #4) should also keep this value in sync in the DOM.
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
