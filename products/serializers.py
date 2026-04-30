from rest_framework import serializers
from .models import Product
from core.utils import calculate_food_miles
class ProductSerializer(serializers.ModelSerializer):
    # producer is set automatically from the logged-in user, not from input
    producer = serializers.ReadOnlyField(source='producer.email')
    
    # Automatically fetches string representation of category in product instead of returning their database ID numbers.
    category_name = serializers.CharField(source='category.name', read_only=True) # Read_only = only use in GET requests, not create or update.


    # Return string representation (list).
    allergen_names = serializers.StringRelatedField(source="allergens", many=True, read_only=True)

    farm_name = serializers.CharField(source='farm.name', read_only=True)
    farm_postcode = serializers.CharField(source='farm.postcode', read_only=True)
    
    season_display_text = serializers.CharField(source='season_display', read_only=True)

    food_miles = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'producer', 'name', 'description', 'price', 'unit',
            'stock_quantity', 'image', 'category', 'category_name', 'farm', 'farm_name', 'farm_postcode', 
            'is_available', 'allergens', 'allergen_names', 'is_year_round', 'season_start', 'season_end', 'season_display_text', 'created_at', 'updated_at', 'food_miles',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_food_miles(self, obj):
        # We need the request object to know WHO is asking (to get their postcode)
        request = self.context.get('request')
        if request and request.user.is_authenticated and hasattr(request.user, 'customer_profile'):
            customer_postcode = request.user.customer_profile.postcode
            farm_postcode = obj.farm.postcode if obj.farm else None

            if customer_postcode and farm_postcode:
                return calculate_food_miles(farm_postcode, customer_postcode)
        return None
