from django import forms
from .models import Category

class ProductAddForm(forms.Form):
    """
    Frontend form for producers to list products.
    Matches teammates product model fields for smooth integration.
    """

    name = forms.CharField(max_length=255, label="Product Name")
    description = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))
    price = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, label="Price (£)")
    unit = forms.CharField(max_length=50, help_text="e.g. kg, box, litre")
    stock_quantity = forms.IntegerField(min_value=0, label="Stock Level")

    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        empty_label="Select Category"
    )

    image = forms.ImageField(label="Product Image", required=False)

    ALLERGEN_CHOICES = [
        ('GLU', 'Gluten'),
        ('MILK', 'Dairy'),
        ('NUTS', 'Nuts'),
        ('SES', 'Sesame'),
    ]
    allergens = forms.MultipleChoiceField(
        choices=ALLERGEN_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Allergen Information"
    )

    is_available = forms.BooleanField(initial=True, required=False, label="Currently Availble?")
    season_start = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Season Start Date"
    )
    season_end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Season End Date"
    )