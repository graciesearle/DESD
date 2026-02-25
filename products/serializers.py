from rest_framework import serializers
from .models import Product, Allergen

class ProductSerializer(serializers.ModelSerializer):
    # producer is set automatically from the logged-in user, not from input
    producer = serializers.ReadOnlyField(source='producer.username')

    class Meta:
        model = Product
        fields = [
            'id', 'producer', 'name', 'description', 'price', 'unit',
            'stock_quantity', 'image', 'allergens', 'is_available',
            'season_start', 'season_end', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
