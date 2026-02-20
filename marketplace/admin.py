from django.contrib import admin
from .models import Category

# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug') # Which columns to display in category list in Admin. (By default only sees name)
    prepopulated_fields = {'slug': ('name',)} # Automatically types slug as you type name (to add a category).