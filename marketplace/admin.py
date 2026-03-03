from django.contrib import admin
from django import forms
from django.contrib.admin.widgets import AdminFileWidget
from .models import Category

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