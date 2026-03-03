from .models import Cart


def cart_item_count(request):
    """
    AB#116
    Template context processor – injects ``cart_item_count`` into every
    template so the navbar can display a live cart counter.
    """
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user, status='active').first()
        if cart:
            count = sum(item.quantity for item in cart.items.all())
            return {'cart_item_count': count}
    return {'cart_item_count': 0}
