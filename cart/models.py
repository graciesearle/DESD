from django.db import models
from django.conf import settings


class Cart(models.Model):
    """
    Represents a shopping cart for a logged-in customer.

    Each user has at most ONE active cart at a time, enforced by a
    UniqueConstraint.  When checkout is implemented the status flips
    to 'ordered' and a fresh cart is created on the next add-to-cart.
    """

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('ordered', 'Ordered'),
        ('abandoned', 'Abandoned'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='carts',
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='active',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'status'],
                condition=models.Q(status='active'),
                name='one_active_cart_per_user',
            )
        ]

    def __str__(self):
        return f"Cart #{self.pk} ({self.user}) – {self.status}"


class CartItem(models.Model):
    """
    A single line-item inside a Cart.

    ``unique_together`` prevents duplicate rows for the same product;
    adding an already-present product increments quantity instead.
    """

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items',
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
    )
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('cart', 'product')]

    def __str__(self):
        return f"{self.quantity}× {self.product.name} in Cart #{self.cart_id}"

    @property
    def pricing_split(self):
        """Returns a dict detailing the quantities and prices for this item."""
        try:
            deal = self.product.surplus_deal
        except Exception:
            deal = None

        if deal and deal.is_active and not deal.is_expired:
            surplus_qty = min(self.quantity, deal.surplus_quantity)
            regular_qty = self.quantity - surplus_qty
            return {
                'surplus_qty': surplus_qty,
                'regular_qty': regular_qty,
                'surplus_price': deal.discounted_price,
                'regular_price': self.product.price,
                'is_split': surplus_qty > 0 and regular_qty > 0
            }
        
        return {
            'surplus_qty': 0,
            'regular_qty': self.quantity,
            'surplus_price': None,
            'regular_price': self.product.price,
            'is_split': False
        }

    @property
    def item_total(self):
        """Line-item total (handles partial surplus deals if quantity exceeds surplus_quantity)."""
        split = self.pricing_split
        total = (split['surplus_qty'] * (split['surplus_price'] or 0)) + (split['regular_qty'] * split['regular_price'])
        return total
