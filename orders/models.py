import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel


def get_producer_display_name(user):
    """
    Return the business name for a producer, falling back to their
    email when no ProducerProfile exists.  Used throughout the orders
    app to avoid repeating the same try/except block.
    """
    try:
        return user.producer_profile.business_name
    except AttributeError:
        return user.email


class Order(SoftDeleteModel):
    """
    Represents a customer order — may span one or many producers.

    Individual producer sub-orders are stored in :model:`ProducerOrder`.
    Every order has at least one ProducerOrder child.

    Lifecycle:  Pending → Confirmed → Dispatched → Delivered
                                      → Cancelled  (at any stage before Delivered)
    """

    class Status(models.TextChoices):
        PENDING    = "PENDING",    "Pending"
        CONFIRMED  = "CONFIRMED",  "Confirmed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED  = "DELIVERED",  "Delivered"
        CANCELLED  = "CANCELLED",  "Cancelled"

    # Unique human-readable order number (e.g. ORD-A3F8B1C2)
    order_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_orders",
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Delivery information
    delivery_address = models.TextField()
    delivery_postcode = models.CharField(max_length=10)

    # Financial fields (snapshot at order time)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    commission_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="Network commission rate applied (e.g. 0.05 = 5%).",
    )
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    producer_payment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Total owed to all producers (subtotal − commission).",
        default=Decimal('0.00'),
    )

    # Special Instructions (from customer)
    special_instructions = models.TextField(
        blank=True,
        null=True,
        help_text="Special delivery instructions or notes for the producer."
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.order_number} – {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self._generate_order_number()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_order_number():
        """Generate a unique order number like ORD-A3F8B1C2."""
        return f"ORD-{uuid.uuid4().hex[:8].upper()}"

    @property
    def is_multi_vendor(self):
        """Return True if the order spans more than one producer.

        Prefer the prefetched ``sub_orders`` cache when available to
        avoid extra queries, and fall back to ``.count()`` so we don't
        load all rows into memory just to answer a boolean.
        """
        prefetched_cache = getattr(self, "_prefetched_objects_cache", {})
        prefetched_sub_orders = prefetched_cache.get("sub_orders")
        if prefetched_sub_orders is not None:
            return len(prefetched_sub_orders) > 1
        return self.sub_orders.count() > 1

    def calculate_financials(self):
        """
        Recalculate totals by aggregating from child ProducerOrders.

        Commission is included in the total (not added on top):
          total = subtotal  (what the customer pays)
          commission = total × rate  (network's cut)
          producer_payment = total − commission  (producer's cut)

        NOTE: this method mutates self but does NOT call save().
        The caller is responsible for persisting the changes.
        """
        sub_orders = self.sub_orders.all()
        self.subtotal = sum((so.subtotal for so in sub_orders), Decimal("0.00"))
        self.commission_amount = sum((so.commission_amount for so in sub_orders), Decimal("0.00"))
        self.total = self.subtotal
        self.producer_payment = (self.total - self.commission_amount).quantize(Decimal("0.01"))


class ProducerOrder(SoftDeleteModel):
    """
    A sub-order linking a parent Order to a single producer.

    Each checkout creates one ProducerOrder per producer in the cart.
    Owns delivery date, per-producer financial split, and status.
    """

    class Status(models.TextChoices):
        PENDING    = "PENDING",    "Pending"
        CONFIRMED  = "CONFIRMED",  "Confirmed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED  = "DELIVERED",  "Delivered"
        CANCELLED  = "CANCELLED",  "Cancelled"

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="sub_orders",
    )
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="producer_sub_orders",
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    delivery_date = models.DateField(
        help_text="Requested delivery date for this producer's items.",
    )

    # Financial snapshot for this producer's portion
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="Network commission rate snapshot (e.g. 0.05 = 5%).",
    )
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    producer_payment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Amount owed to this producer (subtotal − commission).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["delivery_date"]

    def __str__(self):
        return f"SubOrder {self.order.order_number} → {get_producer_display_name(self.producer)}"

    def calculate_financials(self):
        """Recalculate this producer's portion from its own OrderItems.

        NOTE: this method mutates self but does NOT call save().
        The caller is responsible for persisting the changes.
        """
        self.subtotal = sum((item.line_total for item in self.items.all()), Decimal("0.00"))
        rate = Decimal(str(self.commission_rate))
        self.commission_amount = (self.subtotal * rate).quantize(Decimal("0.01"))
        self.producer_payment = (self.subtotal - self.commission_amount).quantize(Decimal("0.01"))


class OrderItem(models.Model):
    """
    Snapshot of a product at the time of purchase.
    Prices are captured so that later catalogue changes don't alter order history.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    producer_order = models.ForeignKey(
        ProducerOrder,
        on_delete=models.CASCADE,
        related_name="items",
        help_text="The producer sub-order this item belongs to.",
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True,
        related_name="order_items",
    )
    product_name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=6, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity}× {self.product_name} (Order {self.order.order_number})"

    def save(self, *args, **kwargs):
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)


class Payment(models.Model):
    """
    Records a payment transaction against an Order.
    Uses a *test mode* stub — no real payment gateway integration.
    """

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        FAILED  = "FAILED",  "Failed"
        PENDING = "PENDING", "Pending"

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="payment",
    )
    transaction_id = models.CharField(
        max_length=40,
        unique=True,
        editable=False,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    payment_method = models.CharField(
        max_length=30,
        default="test_card",
        help_text="Payment method identifier.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment {self.transaction_id} – {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)


class Notification(models.Model):
    """
    Simple in-app notification for producers (and optionally customers).
    """

    class Type(models.TextChoices):
        NEW_ORDER        = "NEW_ORDER",        "New Order"
        ORDER_CONFIRMED  = "ORDER_CONFIRMED",  "Order Confirmed"
        ORDER_CANCELLED  = "ORDER_CANCELLED",  "Order Cancelled"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    notification_type = models.CharField(
        max_length=20,
        choices=Type.choices,
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_notification_type_display()}] → {self.recipient.email}"
