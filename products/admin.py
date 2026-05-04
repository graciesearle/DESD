from django.contrib import admin
from django.utils import timezone
from core.admin import SoftDeleteAdmin
from .models import Product, Allergen, Farm, Review, SurplusDeal

from simple_history.admin import SimpleHistoryAdmin


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
class ProductAdmin(SimpleHistoryAdmin, SoftDeleteAdmin):
    # This controls what columns show up in the list view
    list_display = ('name', 'producer', 'farm', 'price', 'stock_quantity', 'is_available', 'is_year_round', 'season_start', 'season_end')
    
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


@admin.action(description="Hide selected reviews")
def hide_selected_reviews(modeladmin, request, queryset):
    queryset.update(
        is_visible=False,
        moderated_at=timezone.now(),
        moderated_by=request.user,
    )


@admin.action(description="Show selected reviews")
def show_selected_reviews(modeladmin, request, queryset):
    queryset.update(
        is_visible=True,
        moderation_reason="",
        moderated_at=timezone.now(),
        moderated_by=request.user,
    )


@admin.register(Review)
class ReviewAdmin(SimpleHistoryAdmin, SoftDeleteAdmin):
    list_display = (
        "product",
        "customer",
        "rating",
        "is_visible",
        "is_anonymous",
        "created_at",
        "producer_responded_at",
        "is_deleted",
    )
    list_filter = ("rating", "is_visible", "is_anonymous", "is_deleted", "created_at")
    search_fields = (
        "product__name",
        "customer__email",
        "title",
        "body",
        "producer_response",
        "moderation_reason",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "producer_responded_at",
        "moderated_at",
    )
    actions = (hide_selected_reviews, show_selected_reviews)


@admin.register(SurplusDeal)
class SurplusDealAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'discount_percentage',
        'original_price',
        'discounted_price',
        'expires_at',
        'is_active',
        'is_expired',
        'created_at',
    )
    list_filter = ('is_active', 'discount_percentage')
    search_fields = ('product__name', 'product__producer__email', 'note')
    readonly_fields = ('original_price', 'discounted_price', 'created_at')

    def is_expired(self, obj):
        return obj.is_expired
    is_expired.boolean = True
    is_expired.short_description = 'Expired?'