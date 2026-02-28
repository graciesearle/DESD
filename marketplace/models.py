from django.db import models
from django.utils.text import slugify

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