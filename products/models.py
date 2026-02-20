from django.db import models
from django.conf import settings  # To link to the User model
from marketplace.models import Category

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

class Allergen(models.Model):
    """
    TC-015: Critical Priority.
    Simple model to list allergens (e.g., Peanuts, Gluten) so they can be 
    reused across different products.
    """
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    """
    TC-003: Critical Priority (Product Listing)
    TC-016: High Priority (Seasonal Availability)
    """
    # Link to the Producer (the user who created this)
    # use settings.AUTH_USER_MODEL to be safe
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='products'
    )
    
    # Core Fields (TC-003)
    name = models.CharField(max_length=255)
    description = models.TextField()
    price = models.DecimalField(max_digits=6, decimal_places=2) # e.g., 9999.99
    unit = models.CharField(max_length=50, help_text="e.g. kg, box, litre") 
    stock_quantity = models.PositiveIntegerField(default=0)
    
    # Image Field - Using Pillow library
    image = models.ImageField(upload_to='product_images/', blank=False, null=False)

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
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.producer})"