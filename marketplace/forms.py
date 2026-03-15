from django import forms
from datetime import date
from .models import Category
from products.models import Product, Farm

# Pre-set choices for the Unit dropdown
UNIT_CHOICES = [
    ('', 'Select Unit'), # Empty default
    ('kg', 'Kilogram (kg)'),
    ('g', 'Gram (g)'),
    ('litre', 'Litre (L)'),
    ('ml', 'Millilitre (ml)'),
    ('box', 'Box'),
    ('dozen', 'Dozen'),
    ('each', 'Each'),
    ('bunch', 'Bunch'),
]

class FarmAddForm(forms.ModelForm):
    """Frontend form for producers to add their farms. as they cannot list a product before adding a farm (due to food miles calculations)."""
    class Meta:
        model = Farm
        fields = ['name', 'description', 'postcode']
    
    def __init__(self, *args, **kwargs):
        # Extract user so we can validate against their existing farms.
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def clean(self): # Post validation
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        postcode = cleaned_data.get('postcode')

        # Prevent exact duplicate farms for the same producer
        if name and postcode and self.user:
            queryset = Farm.objects.filter(
                producer=self.user,
                name__iexact=name,
                postcode__iexact=postcode
            )
            # Exclude current instance if we are editing an existing farm
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            # If any farm still exists, its a duplicate
            if queryset.exists():
                self.add_error('name', 'You already have another farm registered with this exact name and postcode.')
            
        return cleaned_data

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

    farm = forms.ModelChoiceField(
        queryset=Farm.objects.none(), # Default to none, this is populated in __init__
        empty_label="Select Farm",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    # Upload image (optional) 
    image = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))

    # Override unit to be dropdown
    unit = forms.ChoiceField(choices=UNIT_CHOICES, widget=forms.Select(attrs={'class': 'form-control'}))
    
    class Meta:
        model = Product
        # Fields producer needs to fill out.
        fields = ["name", "description", "price", "unit", "stock_quantity", "low_stock_threshold",
                  "category", "farm", "image", "allergens", "is_available", "season_start", "season_end", "harvest_date"
                ]
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'allergens': forms.CheckboxSelectMultiple(),
            'season_start': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'season_end': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'harvest_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'low_stock_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }
    
    def __init__(self, *args, **kwargs):
        # Pop user out of kwargs before passing to super()
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Security (UX): Only show farms belonging to this specific producer
        if self.user:
            user_farms = Farm.objects.filter(producer=self.user)
            self.fields['farm'].queryset = user_farms # Add the farms to the dropdown.

            # Fallback text if they somehow bypass the redirect.
            if not user_farms.exists():
                self.fields['farm'].empty_label = "No farm registered - Please register a farm first."

    # Verification 
    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        farm = cleaned_data.get('farm')
        price = cleaned_data.get('price')
        stock = cleaned_data.get('stock_quantity')
        is_available = cleaned_data.get('is_available')
        season_start = cleaned_data.get('season_start')
        season_end = cleaned_data.get('season_end')
        harvest_date = cleaned_data.get('harvest_date')

        # Check for duplicate products from the same farm
        if name and farm and self.user:
            # Exclude current instance if we are editing an existing product
            queryset = Product.objects.filter(
                producer=self.user,
                name__iexact=name,
                farm=farm
            )
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            
            if queryset.exists():
                self.add_error('name', f"You already have a product named '{name}' registered for '{farm.name}'.")

        if price is not None and price <= 0:
            self.add_error('price', "Price must be greater than £0.00.")
        
        if stock is not None and stock < 0:
            self.add_error('stock_quantity', "Stock quantity cannot be negative.")

        if is_available and stock is not None and stock == 0:
            self.add_error('is_available', "You cannot mark a product as 'Available' if the stock quantity is 0. Please uncheck this box or add stock.")
        
        if season_start and season_end:
            if season_start > season_end:
                self.add_error('season_end', "Season end date cannot be before the start date.")

        if harvest_date:
            if harvest_date > date.today():
                self.add_error('harvest_date', "Harvest date cannot be set in the future.")
        
        return cleaned_data

    
