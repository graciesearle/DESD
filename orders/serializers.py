from rest_framework import serializers
from .models import OrderItem, ProducerOrder


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['product_name', 'quantity', 'unit_price', 'line_total']


class ProducerSubOrderSerializer(serializers.ModelSerializer):
    """
    Serialises a ProducerOrder (sub-order) with its items.
    Used by the producer API endpoint.
    """
    items = OrderItemSerializer(many=True, read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    customer_email = serializers.EmailField(source='order.customer.email', read_only=True)
    customer_name = serializers.SerializerMethodField()
    delivery_address = serializers.CharField(source='order.delivery_address', read_only=True)
    delivery_postcode = serializers.CharField(source='order.delivery_postcode', read_only=True)
    special_instructions = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(source='order.created_at', read_only=True)

    class Meta:
        model = ProducerOrder
        fields = [
            'order_number',
            'status',
            'customer_email',
            'customer_name',
            'delivery_address',
            'delivery_postcode',
            'special_instructions',
            'delivery_date',
            'subtotal',
            'commission_amount',
            'producer_payment',
            'created_at',
            'items',
        ]

    def get_customer_name(self, obj):
        """Fall back to email when the customer has no profile."""
        try:
            return obj.order.customer.customer_profile.full_name
        except AttributeError:
            return obj.order.customer.email