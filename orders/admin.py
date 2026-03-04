from django.contrib import admin
from core.admin import SoftDeleteAdmin
from .models import Order, OrderItem, Payment, Notification, ProducerOrder


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name", "unit_price", "quantity", "line_total")


class ProducerOrderInline(admin.TabularInline):
    model = ProducerOrder
    extra = 0
    readonly_fields = (
        "producer", "status", "delivery_date",
        "subtotal", "commission_rate", "commission_amount", "producer_payment",
    )
    show_change_link = True


@admin.register(Order)
class OrderAdmin(SoftDeleteAdmin):
    list_display = (
        "order_number", "customer", "status",
        "total", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("order_number", "customer__email")
    readonly_fields = (
        "order_number", "subtotal", "commission_rate",
        "commission_amount", "total", "producer_payment", "created_at", "updated_at",
    )
    inlines = [ProducerOrderInline, OrderItemInline]


class ProducerOrderItemInline(admin.TabularInline):
    model = OrderItem
    fk_name = "producer_order"
    extra = 0
    readonly_fields = ("product", "product_name", "unit_price", "quantity", "line_total")


@admin.register(ProducerOrder)
class ProducerOrderAdmin(SoftDeleteAdmin):
    list_display = (
        "order", "producer", "status", "delivery_date",
        "subtotal", "producer_payment",
    )
    list_filter = ("status", "delivery_date")
    search_fields = ("order__order_number", "producer__email")
    readonly_fields = (
        "subtotal", "commission_rate", "commission_amount",
        "producer_payment", "created_at", "updated_at",
    )
    inlines = [ProducerOrderItemInline]


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
