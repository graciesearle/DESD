from django.conf import settings
from django.db import models
from django.utils.text import slugify

from core.models import SoftDeleteModel, SoftDeleteManager
from simple_history.models import HistoricalRecords

# Create your models here.
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
    """Educational content created by producers (Recipes, Stories, Seasonal Info)."""
    class PostType(models.TextChoices):
        RECIPE = "RECIPE", "Recipe"
        FARM_STORY = "FARM_STORY", "Farm Story"
        SEASONAL_UPDATE = "SEASONAL_UPDATE", "Seasonal Update"
        STORAGE_GUIDE = "STORAGE_GUIDE", "Storage Guide"
    
    producer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="educational_posts")
    title = models.CharField(max_length=200)
    content = models.TextField(help_text="Write your post here. You can include seasonal tips, recipes, etc.")
    post_type = models.CharField(max_length=20, choices=PostType.choices, default=PostType.SEASONAL_UPDATE)
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='liked_posts', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EducationalPostManager()
    history = HistoricalRecords()

    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} by {self.producer.email}"