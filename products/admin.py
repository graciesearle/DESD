from django.contrib import admin
from .models import Product, Allergen

# Allergens section in the admin page
@admin.register(Allergen)
class AllergenAdmin(admin.ModelAdmin):
    list_display = ('name',)

# Products section in the admin page
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    # This controls what columns show up in the list view
    list_display = ('name', 'producer', 'price', 'stock_quantity', 'is_available', 'season_start', 'season_end')
    
    # This adds sidebar filters (Right side of screen)
    list_filter = ('is_available', 'unit', 'allergens')
    
    # This adds a search bar at the top
    search_fields = ('name', 'description', 'producer__username')
    
    # This makes selecting allergens easier (horizontal select box)
    filter_horizontal = ('allergens',)