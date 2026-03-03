from django import forms
from .models import Category
from products.models import Product

class ProductAddForm(forms.ModelForm):
    """
    Frontend form for producers to list products.
    Uses ModelForm for automatic database integration.
    """
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        empty_label="Select Category",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    # Force user to upload image (although db allows it to be empty)
    image = forms.ImageField(required=True, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    
    class Meta:
        model = Product
        # Fields producer needs to fill out.
        fields = ["name", "description", "price", "unit", "stock_quantity",
                  "category", "image", "allergens", "is_available", "season_start", "season_end"
                ]
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'allergens': forms.CheckboxSelectMultiple(),
            'season_start': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'season_end': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }
    
