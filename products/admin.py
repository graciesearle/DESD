from django.contrib import admin
from .models import Product, Allergen, Farm

class SoftDeleteAdmin(admin.ModelAdmin):
    def get_queryset(self, request):  # Return all including deleted items for admins to see
        return self.model.all_objects.all()

# Allergens section in the admin page
@admin.register(Allergen)
class AllergenAdmin(admin.ModelAdmin):
    list_display = ('name',)

# Register Farm Model
@admin.register(Farm)
class FarmAdmin(SoftDeleteAdmin):
    list_display = ('name', 'producer', 'postcode', 'is_deleted')
    search_fields = ('name', 'producer__email', 'postcode')
    list_filter = ('is_deleted',)

# Products section in the admin page
@admin.register(Product)
class ProductAdmin(SoftDeleteAdmin):
    # This controls what columns show up in the list view
    list_display = ('name', 'producer', 'farm', 'price', 'stock_quantity', 'is_available', 'season_start', 'season_end')
    
    # This adds sidebar filters (Right side of screen)
    list_filter = ('is_available', 'unit', 'allergens', 'farm')
    
    # This adds a search bar at the top
    search_fields = ('name', 'description', 'producer__email', 'farm__name')  # changed producer__username to __email as we use CustomUser
    
    # This makes selecting allergens easier (horizontal select box)
    filter_horizontal = ('allergens',)

    # Restrict dropdowns to only show the producer's own farm
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "farm": # only run if field being rendered is farm.
            if not request.user.is_superuser:
                kwargs["queryset"] = Farm.objects.filter(producer=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)