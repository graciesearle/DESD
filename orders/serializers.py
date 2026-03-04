from rest_framework import serializers
from .models import Order, OrderItem

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields =['product_name', 'quantity', 'unit_price', 'line_total']

class ProducerOrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields =[
            'order_number',
            'status',
            'customer_email',
            'customer_name',
            'delivery_address',
            'delivery_postcode',
            'delivery_date',
            'total',
            'producer_payment',
            'created_at',
            'items'
        ]

    def get_customer_name(self, obj):
        try:
            return obj.customer.customer_profile.full_name
        except Exception:
            return "N/A"