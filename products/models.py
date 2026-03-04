from django.db import models
from django.conf import settings  # To link to the User model
from django.utils import timezone
from django.db.models import Q
from marketplace.models import Category
from core.models import SoftDeleteModel, SoftDeleteManager

class ProductManager(SoftDeleteManager):
    def active_and_in_season(self):
        """
        Returns QuerySet of products that are:
        1. Marked Available
        2. Currently in season. (Current date is within season_start and season_end (if set))
        3. Not deleted (handled automatically by SoftDeleteManager)
        """
        # Get todays date
        today = timezone.now().date()

        # Filter requirements:
        # - Must be marked available
        # - (Start date is not set OR start_date <= Today) AND
        # - (End date is not set OR end_date >= Today)
        
        return (
            self.select_related('category', 'producer', 'farm').prefetch_related('allergens').filter( # fetch their category, producer and farm while you are fetching products
                Q(is_available=True) & # Q for complex queries, Product is ON
                (Q(season_start__isnull=True) | Q(season_start__lte=today)) &
                (Q(season_end__isnull=True) | Q(season_end__gte=today)) &
                Q(producer__is_active=True) & # Producer account is ON
                Q(farm__is_deleted=False) # Farm is ON
            )
        )

def get_default_category():
    """
    Returns the 'Uncategorised' category object.
    Creates it if it doesn't exist.
    """
    # get_or_create returns a tuple (object, created_bool) we only want object
    return Category.objects.get_or_create(
        name="Uncategorised",
        defaults={'description': 'Items whose category is not assigned.'}
    )[0]


class Farm(SoftDeleteModel):
    """
    Represents the origin of the food (To satisfy the "farm origin" input in TC004 Browse & Categorise)
    Crucial for the Food Miles postcode calculation.
    """
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, # Incase Admin actually hard deletes producer then hard delete farm (does not run on soft deletes)
        related_name='farms'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, help_text="Tell the community about your farm.")

    # Required for food miles
    postcode = models.CharField(max_length=8, help_text="e.g., BS1 5TR")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Allergen(models.Model):
    """
    TC-015: Critical Priority.
    Simple model to list allergens (e.g., Peanuts, Gluten) so they can be 
    reused across different products.
    """
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class Product(SoftDeleteModel):
    """
    TC-003: Critical Priority (Product Listing)
    TC-016: High Priority (Seasonal Availability)
    """
    objects = ProductManager() # Replace default
    
    # Link to the Producer (the user who created this)
    # use settings.AUTH_USER_MODEL to be safe
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='products'
    )

    farm = models.ForeignKey(
        Farm,
        on_delete=models.CASCADE, # Incase Admin hard deletes farm, then hard-delete product (does not run on soft-delete)
        null=False,
        blank=False,
        related_name='products',
        help_text="Which farm did this come from?"
    )
    
    # Core Fields (TC-003)
    name = models.CharField(max_length=255)
    description = models.TextField()
    price = models.DecimalField(max_digits=6, decimal_places=2) # e.g., 9999.99
    unit = models.CharField(max_length=50, help_text="e.g. kg, box, litre") 
    stock_quantity = models.PositiveIntegerField(default=0)
    
    # Image Field - Using Pillow library
    image = models.ImageField(upload_to='product_images/', blank=True, null=True)

    # TC-015: Allergen Info (Many-to-Many)
    # This allows one product to have multiple allergens, and one allergen to be on multiple products.
    allergens = models.ManyToManyField(Allergen, blank=True)

    # Category (Each product belongs to one category, many-to-one relationship)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET(get_default_category),
        related_name='products', # cleaner name to access all products in a category 'category.products
        null=False,
        blank=False
    )

    # TC-016: Seasonal Availability
    is_available = models.BooleanField(default=True, verbose_name="Currently Available?")
    season_start = models.DateField(null=True, blank=True, help_text="When does the season start?")
    season_end = models.DateField(null=True, blank=True, help_text="When does the season end?")

    # TC-004: Harvest Date
    harvest_date = models.DateField(null=True, blank=True, help_text="When was this harvested or prepared?")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.producer})"