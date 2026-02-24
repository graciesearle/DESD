from rest_framework import serializers
from products.models import Product

class ProductSerializer(serializers.ModelSerializer):
    # Automatically fetches string representation of category in product instead of returning their database ID numbers.
    category_name = serializers.CharField(source='category.name', read_only=True) # Read_only = only use in GET requests, not create or update.
    
    producer_username = serializers.CharField(source='producer.username', read_only=True)

    # Return string representation (list).
    allergens = serializers.StringRelatedField(many=True)

    class Meta:
        model = Product
        fields = [ # Fields included in API responses
            'id', 'name', 'description', 'price', 'unit', 'stock_quantity', 'image', 'category_name', 'is_available',
            'allergens', 'season_start', 'season_end', 'producer_username'
        ]
