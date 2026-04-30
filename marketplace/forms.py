from django import forms
from datetime import date
from .models import Category, EducationalPost, Recipe
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

MONTH_CHOICES = [(f"{i:02d}", date(2000, i, 1).strftime('%B')) for i in range(1, 13)]
DAY_CHOICES = [(f"{i:02d}", str(i)) for i in range(1, 32)]

LISTING_STATUS_CHOICES = [
    (True, 'Active (Visible to customers)'),
    (False, 'Hidden / Unavailable (Completely hidden from customer browsing)')
]

CYCLE_CHOICES = [
    (True, 'Available Year-Round'),
    (False, 'Seasonal Product')
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
    
    is_available = forms.TypedChoiceField(
        choices=LISTING_STATUS_CHOICES, 
        widget=forms.RadioSelect, 
        coerce=lambda x: x == 'True',
        label="Listing Status"
    )

    is_year_round = forms.TypedChoiceField(
        choices=CYCLE_CHOICES, 
        widget=forms.RadioSelect, 
        coerce=lambda x: x == 'True',
        label="Harvest/Production Cycle"
    )

    season_start_month = forms.ChoiceField(choices=[('', 'Month')] + MONTH_CHOICES, required=False, label="Start Month")
    season_end_month = forms.ChoiceField(choices=[('', 'Month')] + MONTH_CHOICES, required=False, label="End Month")

    low_stock_threshold = forms.IntegerField(
        min_value=0, 
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        help_text="We'll notify you when your stock dips below this number.",
        label="Low Stock Alert Threshold"
    )

    stock_quantity = forms.IntegerField(
        min_value=0, 
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        label="Current Stock Quantity"
    )

    allergen_info_confirmed = forms.BooleanField(
        required=True,
        label="Allergen information reviewed",
        help_text="You must either select relevant allergens or confirm that there are no common allergens.",
    )

    class Meta:
        model = Product
        # Fields producer needs to fill out.
        fields = ["name", "description", "price", "unit", "stock_quantity", "low_stock_threshold",
                  "category", "farm", "image", "allergens", "is_available", "is_year_round", "season_start", "season_end", "harvest_date"
                ]
        
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'allergens': forms.CheckboxSelectMultiple(),
            'harvest_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'season_start': forms.HiddenInput(),
            'season_end': forms.HiddenInput(),
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

        if self.instance and self.instance.pk:
            self.initial['allergen_info_confirmed'] = True
            
            # --- Field Rebind Fixes ---
            if self.instance.unit:
                unit_keys = [c[0] for c in UNIT_CHOICES]
                if self.instance.unit not in unit_keys:
                    self.fields['unit'].choices = UNIT_CHOICES + [(self.instance.unit, self.instance.unit.capitalize())]
                self.initial['unit'] = self.instance.unit

            if not self.instance.season_start and not self.instance.season_end:
                self.initial['is_year_round'] = True
            else:
                self.initial['is_year_round'] = False
                
            if self.instance.season_start:
                try:
                    s_month = self.instance.season_start.split('-')[0]
                    self.initial['season_start_month'] = s_month
                except ValueError:
                    pass
            if self.instance.season_end:
                try:
                    e_month = self.instance.season_end.split('-')[0]
                    self.initial['season_end_month'] = e_month
                except ValueError:
                    pass

    # Verification 
    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        farm = cleaned_data.get('farm')
        price = cleaned_data.get('price')
        stock = cleaned_data.get('stock_quantity')
        is_available = cleaned_data.get('is_available')
        is_year_round = cleaned_data.get('is_year_round')
        
        season_start_month = cleaned_data.get('season_start_month')
        season_end_month = cleaned_data.get('season_end_month')

        harvest_date = cleaned_data.get('harvest_date')
        allergens = cleaned_data.get('allergens')
        allergen_info_confirmed = cleaned_data.get('allergen_info_confirmed')

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
        
        if not is_year_round:
            if not season_start_month and not season_end_month:
                self.add_error('season_start_month', "Please specify a complete start or end date, or select 'Available Year-Round'.")
            
            end_days = {
                '01': '31', '02': '29', '03': '31', '04': '30',
                '05': '31', '06': '30', '07': '31', '08': '31',
                '09': '30', '10': '31', '11': '30', '12': '31'
            }
            
            if season_start_month:
                cleaned_data['season_start'] = f"{season_start_month}-01"
            if season_end_month:
                cleaned_data['season_end'] = f"{season_end_month}-{end_days.get(season_end_month, '30')}"
        else:
            cleaned_data['season_start'] = None
            cleaned_data['season_end'] = None

        if harvest_date:
            if harvest_date > date.today():
                self.add_error('harvest_date', "Harvest date cannot be set in the future.")

        if not allergen_info_confirmed:
            self.add_error(
                'allergen_info_confirmed',
                'Please confirm allergen information before listing this product.',
            )

        # Producers must make an explicit food-safety declaration.
        # Empty allergens are allowed only when disclosure has been confirmed.
        if allergens is None:
            self.add_error(
                'allergens',
                'Please provide allergen information for this product.',
            )
        
        return cleaned_data


class EducationalPostForm(forms.ModelForm):
    """Frontend form for producers to post their educational content."""
    send_email_alert = forms.BooleanField(
        required=False,
        initial=True,
        label="Notify Subscribers",
        help_text="Send an email notification to customers subscribed to your farm."
    )

    image = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = EducationalPost
        fields = ['title', 'post_type', 'content','image']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'post_type': forms.Select(attrs={'class': 'form-control'}),
        }

class RecipeForm(forms.ModelForm):
    """
    Frontend form for producers to create and publish recipes.
    Linked products are filtered to only show the producer's own products.
    """

    send_email_alert = forms.BooleanField(
        required=False,
        initial=True,
        label="Notify Subscribers",
        help_text="Send an email notification to customers subscribed to your farm."
    )

    class Meta:
        model = Recipe
        fields = ['title', 'description', 'ingredients', 'instructions', 'image', 'seasonal_tag', 'linked_products', 'is_published']
        widgets = {
            'title':        forms.TextInput(attrs={'class': 'form-control'}),
            'description':  forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'ingredients':  forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'List ingredients, one for each line.'}),
            'instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 6}),
            'seasonal_tag': forms.Select(attrs={'class': 'form-control'}),
            'linked_products': forms.CheckboxSelectMultiple(),
            'is_published': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        # Pop user so we can filter linked_products to this producer only
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Only show this producer's own products as linkable
        if self.user:
            self.fields['linked_products'].queryset = Product.objects.filter(
                producer=self.user,
                is_available=True,
            )
            self.fields['linked_products'].label_from_instance = lambda obj: obj.name

    def clean_title(self):
        title = self.cleaned_data.get('title')
        # Prevent duplicate recipe titles for the same producer
        if title and self.user:
            queryset = Recipe.objects.filter(
                producer=self.user,
                title__iexact=title
            )
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise forms.ValidationError("You already have a recipe with this title.")
        return title

    def clean(self):
        cleaned_data = super().clean()
        instructions = cleaned_data.get('instructions')
        ingredients = cleaned_data.get('ingredients')

        if instructions and len(instructions.strip()) < 20:
            self.add_error('instructions', "Please provide more detailed cooking instructions.")

        if ingredients and len(ingredients.strip()) < 5:
            self.add_error('ingredients', "Please provide at least one ingredient.")

        return cleaned_data