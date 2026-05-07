from decimal import Decimal

from django.db import models
from django.contrib.postgres.indexes import GinIndex
from django.conf import settings  # To link to the User model
from django.utils import timezone
from django.db.models import Q
from django.core.validators import MinValueValidator, MaxValueValidator
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
            self.select_related('category', 'producer', 'farm', 'organic_certificate').prefetch_related('allergens').filter( # fetch their category, producer and farm while you are fetching products
                Q(is_available=True) & # Q for complex queries, Product is ON
                Q(producer__is_active=True) & # Producer account is ON
                ~Q(producer__producer_profile__vacation_mode=True) & # Vacation mode is OFF
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

    class Meta:
        indexes = [
            GinIndex(
                fields=['name'],
                name='farm_name_gin_idx',
                opclasses=['gin_trgm_ops']
            ),
        ]

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


class OrganicCertificate(models.Model):
    """Represents a single organic certificate a producer can assign to one product."""
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='organic_certificates',
    )
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

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

    organic_certificate = models.ForeignKey(
        OrganicCertificate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        help_text="Select the organic certificate that applies to this product.",
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

    class Meta:
        indexes = [
            # Without GIN: the database has to search every row until it finds a match.
            # With GIN: it chops words and saves them into 3-letter chunks called Trigrams
            # Example: "TOMATO" -> chunks: "Tom", "OMA", "MAT", "ATO"
            # DB now builds an index, if a typo happens ("TOMTO"), the db compares the chunk and see "TOM" in common, jumping instantly to the product.
            GinIndex(
                fields=['name'],
                name='prod_name_gin_idx',
                opclasses=['gin_trgm_ops']
            ),
            GinIndex(
                fields=['description'],
                name='produ_desc_gin_idx',
                opclasses=['gin_trgm_ops']
            ),
        ]

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

    @property
    def effective_price(self):
        """Return the surplus deal price if an active deal exists, else the normal price."""
        try:
            deal = self.surplus_deal
        except SurplusDeal.DoesNotExist:
            return self.price
        if deal and deal.is_active and not deal.is_expired:
            return deal.discounted_price
        return self.price

    @property
    def has_active_surplus_deal(self):
        """Check if this product has an active, non-expired surplus deal."""
        try:
            deal = self.surplus_deal
            return deal.is_active and not deal.is_expired
        except SurplusDeal.DoesNotExist:
            return False


class Review(SoftDeleteModel):
    """
    Customer review for a purchased product.

    Reviews are limited to one active review per customer/product pair,
    and are only surfaced on customer-facing pages when visible.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
        help_text="Delivered order that verified this purchase.",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    title = models.CharField(max_length=120)
    body = models.TextField(max_length=2000)
    is_anonymous = models.BooleanField(default=False)

    # Moderation controls
    is_visible = models.BooleanField(
        default=True,
        help_text="Hidden reviews are excluded from customer-facing views.",
    )
    moderation_reason = models.CharField(max_length=255, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderated_reviews",
    )
    moderated_at = models.DateTimeField(null=True, blank=True)

    # Producer response
    producer_response = models.TextField(blank=True, max_length=1500)
    producer_responded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "product"],
                condition=Q(is_deleted=False),
                name="uniq_active_review_per_customer_product",
            ),
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
        ]
        indexes = [
            models.Index(fields=["product", "created_at"]),
            models.Index(fields=["product", "is_visible"]),
        ]

    def __str__(self):
        return f"{self.product.name} review by {self.customer.email}"

    @property
    def reviewer_display_name(self):
        if self.is_anonymous:
            return "Anonymous Customer"
        try:
            return self.customer.customer_profile.display_name
        except AttributeError:
            return self.customer.email


class SurplusDeal(models.Model):
    """
    A time-limited discount on an existing product to reduce food waste.
    One active deal per product at a time (enforced by OneToOneField).
    Producers can set a 10–50% discount and an expiry window.
    """
    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='surplus_deal',
    )
    discount_percentage = models.PositiveIntegerField(
        validators=[MinValueValidator(10), MaxValueValidator(50)],
        help_text="Discount percentage (10–50%)."
    )
    original_price = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Snapshot of the product price when the deal was created."
    )
    discounted_price = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text="Calculated discounted price."
    )
    note = models.TextField(
        blank=True,
        help_text="e.g. 'Perfect condition, must sell quickly to avoid waste'"
    )
    best_before_date = models.DateField(
        help_text="Best before date (date only)."
    )
    expires_at = models.DateTimeField(
        help_text="When this surplus deal automatically expires."
    )
    surplus_quantity = models.PositiveIntegerField(
        help_text="Number of items available at the surplus discount.",
        default=0
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Producer can deactivate if stock sells out."
    )

    def save(self, *args, **kwargs):
        """Auto-calculate original and discounted prices from the product."""
        self.original_price = self.product.price
        discount = Decimal(self.discount_percentage) / Decimal('100')
        self.discounted_price = (self.original_price * (1 - discount)).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        """Check if the deal has passed its expiry time or run out of quantity."""
        return timezone.now() >= self.expires_at or self.surplus_quantity <= 0

    @property
    def time_remaining(self):
        """Human-readable time remaining on the deal."""
        delta = self.expires_at - timezone.now()
        if delta.total_seconds() <= 0:
            return "Expired"
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        if hours > 0:
            return f"{hours}h {minutes}m remaining"
        return f"{minutes}m remaining"

    class Meta:
        verbose_name = "Surplus Deal"
        verbose_name_plural = "Surplus Deals"

    def __str__(self):
        return f"{self.discount_percentage}% off {self.product.name} (expires {self.expires_at.strftime('%d %b %Y %H:%M')})"