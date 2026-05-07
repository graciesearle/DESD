from django.contrib import admin
from django import forms
from django.contrib.admin.widgets import AdminFileWidget
from .models import Category, EducationalPost, Recipe, Comment 
from core.admin import SoftDeleteAdmin
from simple_history.admin import SimpleHistoryAdmin

class CategoryAdminForm(forms.ModelForm):
    # Enforce image requirement only in Admin UI (database can still hold null for uncategorised)
    image = forms.ImageField(widget=AdminFileWidget, required=True, help_text="Mandatory for the marketplace carousel.")

    class Meta:
        model = Category
        fields = '__all__'

# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = ('name', 'slug') # Which columns to display in category list in Admin. (By default only sees name)
    prepopulated_fields = {'slug': ('name',)} # Automatically types slug as you type name (to add a category).

@admin.register(EducationalPost)
class EducationalPostAdmin(SimpleHistoryAdmin, SoftDeleteAdmin):
    list_display = ('title', 'producer', 'post_type', 'created_at', 'is_deleted')
    list_filter = ('post_type', 'is_deleted', 'created_at')
    search_fields = ('title', 'content', 'producer__email', 'producer__producer_profile__business_name')

@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display       = ('title', 'producer', 'seasonal_tag', 'is_published', 'created_at')
    list_filter        = ('seasonal_tag', 'is_published')
    filter_horizontal  = ('linked_products',)

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'post', 'recipe', 'is_reply', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('body', 'author__email')