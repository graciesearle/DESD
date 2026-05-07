from django.conf import settings
from django.db import models
from django.utils.text import slugify

from core.models import SoftDeleteModel, SoftDeleteManager
from simple_history.models import HistoricalRecords

class ModerationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected/Hidden'

class Category(models.Model):
    """A model that represents a category. Consists of a name and a description."""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, help_text="Optional description of the category")
    
    # A URL-friendly id used for filtering products in marketplace (e.g. /marketplace/?category=vegetables), more SEO friendly.
    slug = models.SlugField(unique=True, blank=True, help_text="Used to filter in the URL (Automatically filled)") 

    # Allow admins to upload a category image. (Make it mandatory so carousel is not empty)
    image = models.ImageField(upload_to='category_images/', null=True, blank=True) # Allow 'Uncategorised' to be created without image.

    class Meta:
        verbose_name_plural = "Categories" # As this would automatically pluralise as Categorys
    
    def save(self, *args, **kwargs):
        if not self.slug: # Don't overwrite an existing slug.
            self.slug = slugify(self.name) # Converts it to a slug (lowercase, spaces handled, etc...).
        super().save(*args, **kwargs) # Calls djangos original save method to save to database.

    def __str__(self):
        return self.name
    
class EducationalPostManager(SoftDeleteManager):
    def active_posts(self):
        """Only return posts that are not soft-deleted and where the producer's account is still active."""
        return self.get_queryset().filter(producer__is_active=True)

class EducationalPost(SoftDeleteModel):
    """Educational content created by producers (Stories, Seasonal Info)."""
    class PostType(models.TextChoices):
        FARM_STORY = "FARM_STORY", "Farm Story"
        SEASONAL_UPDATE = "SEASONAL_UPDATE", "Seasonal Update"
        STORAGE_GUIDE = "STORAGE_GUIDE", "Storage Guide"
    
    producer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="educational_posts")
    title = models.CharField(max_length=200)
    content = models.TextField(help_text="Write your post here. You can include seasonal tips, recipes, etc.")
    post_type = models.CharField(max_length=20, choices=PostType.choices, default=PostType.SEASONAL_UPDATE)
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='liked_posts', blank=True)
    image = models.ImageField(upload_to='post_images/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EducationalPostManager()
    history = HistoricalRecords()

    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} by {self.producer.email}"
    
class Recipe(SoftDeleteModel):
    """ Producers can share recipes linked to their own products and recipes appear on the relevant product detail pages."""

    SEASON_CHOICES = [
        ('spring',    'Spring'),
        ('summer',    'Summer'),
        ('autumn',    'Autumn'),
        ('winter',    'Winter'),
        ('year_round','Year Round'),
    ]

    history = HistoricalRecords()

    # Producer ownership — only producers can create recipes
    producer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recipes',
        limit_choices_to={'role': 'PRODUCER'},
    )

    # Link recipe to products from producer's inventory
    linked_products = models.ManyToManyField(
        'products.Product',
        blank=True,
        related_name='recipes',
        help_text="Products featured in this recipe. Will appear on their product pages.",
    )

    # Core fields
    title        = models.CharField(max_length=255)
    description  = models.TextField(help_text="Brief intro to the recipe.")
    ingredients  = models.TextField(help_text="List ingredients, one for each line.")
    instructions = models.TextField(help_text="Step-by-step cooking instructions.")
    image        = models.ImageField(upload_to='recipe_images/', blank=True, null=True)
    seasonal_tag = models.CharField(max_length=20, choices=SEASON_CHOICES, default='year_round')


    # "Select seasonal tag: Autumn/Winter"
    seasonal_tag = models.CharField(
        max_length=20,
        choices=SEASON_CHOICES,
        default='year_round',
    )

    # "Publish recipe" — producers draft before going live
    is_published = models.BooleanField(
        default=False,
        help_text="Only published recipes are visible to customers.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    saved_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='saved_recipes',
        help_text="Customers who have saved this recipe.",
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'Recipe'
        verbose_name_plural = 'Recipes'

    def __str__(self):
        return f"{self.title} by {self.producer.producer_profile.business_name}"
    
class Comment(SoftDeleteModel):
    """ Comment section for customers and producers can reply to comments on EducationalPosts and Recipes. """

    # Link to either a post OR a recipe
    post = models.ForeignKey(
        EducationalPost,
        on_delete=models.CASCADE,
        related_name='comments',
        null=True,
        blank=True,
    )
    recipe = models.ForeignKey(
        Recipe,
        on_delete=models.CASCADE,
        related_name='comments',
        null=True,
        blank=True,
    )

    # The user who wrote the comment 
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='comments',
    )

    # Producer reply
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
        help_text="Set if this is a producer reply to a customer comment.",
    )

    body = models.TextField(max_length=1000)

    # Moderation fields
    moderation_status = models.CharField(
        max_length=20,
        choices=ModerationStatus.choices,
        default=ModerationStatus.PENDING,
        help_text="Pending and Approved comments are publicly visible. Rejected comments are hidden.",
    )
    moderation_reason = models.CharField(max_length=255, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderated_comments",
    )
    moderated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.email} on {self.post or self.recipe}"

    @property
    def is_reply(self):
        return self.parent is not None