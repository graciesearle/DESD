from rest_framework import serializers
from .models import Product, Allergen

class ProductSerializer(serializers.ModelSerializer):
    # producer is set automatically from the logged-in user, not from input
    producer = serializers.ReadOnlyField(source='producer.email')
    
    # Automatically fetches string representation of category in product instead of returning their database ID numbers.
    category_name = serializers.CharField(source='category.name', read_only=True) # Read_only = only use in GET requests, not create or update.


    # Return string representation (list).
    allergen_names = serializers.StringRelatedField(source="allergens", many=True, read_only=True)

    farm_name = serializers.CharField(source='farm.name', read_only=True)
    farm_postcode = serializers.CharField(source='farm.postcode', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'producer', 'name', 'description', 'price', 'unit',
            'stock_quantity', 'image', 'category', 'category_name', 'farm', 'farm_name', 'farm_postcode', 
            'is_available', 'allergens', 'allergen_names', 'is_year_round', 'season_start', 'season_end', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
