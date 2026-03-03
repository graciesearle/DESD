import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Order(models.Model):
    """
    Represents a customer order for products from a **single** producer.

    Lifecycle:  Pending ➜ Confirmed ➜ Dispatched ➜ Delivered
                                      ➜ Cancelled  (at any stage before Delivered)
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
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="producer_orders",
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Delivery information
    delivery_address = models.TextField()
    delivery_postcode = models.CharField(max_length=10)
    delivery_date = models.DateField(
        help_text="Requested delivery date (must respect producer lead time).",
    )

    # Financial fields (snapshot at order time)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    commission_rate = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        help_text="Network commission rate applied (e.g. 0.05 = 5%).",
    )
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    producer_payment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Amount owed to the producer (subtotal − commission kept by network).",
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

    def calculate_financials(self):
        """
        Recalculate totals from current line items.
        Call this *after* all OrderItems have been added.

        Commission is included in the total (not added on top):
          total = subtotal  (what the customer pays)
          commission = total × rate  (network's cut)
          producer_payment = total − commission  (producer's cut)
        """
        self.subtotal = sum(
            item.line_total for item in self.items.all()
        )
        rate = Decimal(str(self.commission_rate))
        self.total = self.subtotal
        self.commission_amount = (self.total * rate).quantize(Decimal("0.01"))
        self.producer_payment = (self.total - self.commission_amount).quantize(Decimal("0.01"))


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
