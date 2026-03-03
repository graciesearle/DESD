from django.contrib import admin
from .models import Order, OrderItem, Payment, Notification


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "unit_price", "quantity", "line_total")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number", "customer", "producer", "status",
        "total", "delivery_date", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("order_number", "customer__email", "producer__email")
    readonly_fields = (
        "order_number", "subtotal", "commission_rate",
        "commission_amount", "total", "producer_payment", "created_at", "updated_at",
    )
    inlines = [OrderItemInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_id", "order", "amount", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("transaction_id",)
    readonly_fields = ("transaction_id", "created_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("recipient__email", "message")
