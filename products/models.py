from django.db import models
from django.conf import settings  # To link to the User model
from django.utils import timezone
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from decimal import Decimal
from marketplace.models import Category
from core.models import SoftDeleteModel, SoftDeleteManager

from simple_history.models import HistoricalRecords

class ProductManager(SoftDeleteManager):
    def active_and_in_season(self):
        """
        Returns QuerySet of products that are:
        1. Marked Available
        2. Currently in season. (Current date is within season_start and season_end (if set)) (or available year round)
        3. Not deleted (handled automatically by SoftDeleteManager)
        """
        # Get todays date formatted as MM-DD
        today = timezone.now().date()
        current_md = today.strftime('%m-%d')

        return (
            self.select_related('category', 'producer', 'farm').prefetch_related('allergens').filter( # fetch their category, producer and farm while you are fetching products
                Q(is_available=True) & # Q for complex queries, Product is ON
                Q(producer__is_active=True) & # Producer account is ON
                Q(farm__is_deleted=False) & # Farm is ON
                (
                    Q(is_year_round=True) | # Option A: year round OR
                    (Q(season_start__isnull=True) & Q(season_end__isnull=True)) | # Option B: no dates set
                    ( # Option C: Standard intra-year season (e.g. 05-01 to 09-30)
                        Q(season_start__lte=models.F('season_end')) &
                        Q(season_start__lte=current_md, season_end__gte=current_md)
                    ) |
                    ( # Option D: Cross-year season (e.g. 11-01 to 02-28)
                        Q(season_start__gt=models.F('season_end')) &
                        (Q(season_start__lte=current_md) | Q(season_end__gte=current_md))
                    )
                )
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

    history = HistoricalRecords() # We only need to initialise in the model and it will generate a table. (tracks any create, update or delete operations)
    
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
    is_year_round = models.BooleanField(default=False, verbose_name="Available all year round?", help_text="If checked, seasonal start and end dates will be ignored.")
    season_start = models.CharField(max_length=5, null=True, blank=True, help_text="MM-DD (e.g., 06-01)")
    season_end = models.CharField(max_length=5, null=True, blank=True, help_text="MM-DD (e.g., 08-31)")

    # TC-004: Harvest Date
    harvest_date = models.DateField(null=True, blank=True, help_text="When was this harvested or prepared?")

    # Stock Alerts
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        help_text="Alert me when stock drops to or below this number."
    )
    low_stock_notified = models.BooleanField(
        default=False,
        help_text="Internal flag to prevent spamming emails."
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.is_year_round:
            self.season_start = None
            self.season_end = None
        # Auto reset notification flag if stock goes back above the threshold
        if self.stock_quantity > self.low_stock_threshold:
            self.low_stock_notified = False
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.producer})"


    @property
    def season_display(self):
        """Format the MM-DD string into a readable format e.g., '01 Jun' or returns 'Year-round'"""
        if not self.season_start and not self.season_end:
            return "Year-round"
            
        def format_md(md_str):
            try:
                m, d = md_str.split('-')
                import datetime
                month_name = datetime.date(2000, int(m), 1).strftime('%B')
                d_int = int(d)
                if d_int <= 5:
                    return f"Start of {month_name}"
                elif d_int >= 25:
                    return f"End of {month_name}"
                else:
                    return f"Mid {month_name}"
            except (ValueError, TypeError, AttributeError):
                return ""
                
        if self.season_start and self.season_end:
            return f"{format_md(self.season_start)} \u2013 {format_md(self.season_end)}"
        elif self.season_start:
            return f"From {format_md(self.season_start)}"
        elif self.season_end:
            return f"Until {format_md(self.season_end)}"
        return "Year-round"

    @property
    def stock_status(self):
        """Return (color_code, label) based on urgency."""
        if self.stock_quantity == 0:
            return "critical", "Out of Stock"
        
        if self.low_stock_threshold == 0:
            return "healthy", "Healthy" # division by zero
        
        # Calculate percentage of threshold remaining.
        ratio = (self.stock_quantity / self.low_stock_threshold)

        if ratio <= 0.2:
            return "critical", "Critical"
        elif ratio <= 1.0:
            return "low", "Low"
        else:
            return "healthy", "Healthy"


class ProductBatch(models.Model):
    """A distinct quality-graded lot of a parent product."""

    class Grade(models.TextChoices):
        A = "A", "Grade A (Premium)"
        B = "B", "Grade B (Standard)"
        C = "C", "Grade C (Clearance)"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    grade = models.CharField(max_length=1, choices=Grade.choices)
    stock_quantity = models.PositiveIntegerField(default=0)
    base_price = models.DecimalField(max_digits=6, decimal_places=2, help_text="Price before any AI discount.")
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="AI-recommended discount (0-100).")
    final_price = models.DecimalField(max_digits=6, decimal_places=2, help_text="Computed: base_price * (1 - discount/100).")
    inference_log = models.ForeignKey(
        "ai_engineering.InferenceRequestLog",
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name="batches",
        help_text="The AI scan that created this lot."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Product Batches"
        constraints = [
            models.UniqueConstraint(fields=['inference_log', 'product'], name='unique_batch_per_inference')
        ]

    def save(self, *args, **kwargs):
        base_val = Decimal(str(self.base_price))
        disc_val = Decimal(str(self.discount_percent))
        if self.stock_quantity == 0:
            self.is_active = False
        self.final_price = (base_val * (Decimal("1") - disc_val / Decimal("100"))).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)
        sync_product_stock_from_active_batches(self.product_id)

    def delete(self, *args, **kwargs):
        product_id = self.product_id
        super().delete(*args, **kwargs)
        sync_product_stock_from_active_batches(product_id)

    def __str__(self):
        return f"{self.product.name} - Grade {self.grade} ({self.stock_quantity})"


def sync_product_stock_from_active_batches(product_id):
    """Recompute Product.stock_quantity from active ProductBatch rows."""
    if not product_id:
        return 0

    total_stock = ProductBatch.objects.filter(
        product_id=product_id,
        is_active=True,
    ).aggregate(total=Coalesce(Sum("stock_quantity"), 0))["total"]
    total_stock = int(total_stock or 0)

    product = Product.objects.only("id", "low_stock_threshold", "low_stock_notified").filter(pk=product_id).first()
    if not product:
        return total_stock

    updates = {"stock_quantity": total_stock}
    if total_stock > product.low_stock_threshold and product.low_stock_notified:
        updates["low_stock_notified"] = False

    Product.objects.filter(pk=product_id).update(**updates)
    return total_stock