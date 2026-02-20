from django.shortcuts import render, redirect
from .models import Category
from .forms import ProductAddForm

# Create your views here.
def product_list(request):
    """
    Displays the marketplace (products) with sidebar filters.
    Includes Mock Data (until a model is built) to simulate database records.
    """

    # Fetch all categories from DB
    categories = Category.objects.all()

    # Mock Data (Switch here - once model is ready).
    products = [
        {
            'id': 1,
            'name': 'Baby Carrots',
            'description': 'Sweet and crunchy organic baby carrots.',
            'category': 'vegetables',
            'price': 2.99,
            'unit': '500g',
            'producer': 'Community Farm',
            'stock_quantity': 15,
            'image': 'https://placehold.co/150', # Placeholder image
            'allergens': [],
            'is_available': True,
            'season_end': '2026-2-30',
        },
        {
            'id': 2,
            'name': 'White Sourdough',
            'description': 'Slow fermented bread with a crispy crust.',
            'category': 'bakery',
            'price': 3.50,
            'unit': 'Loaf',
            'producer': 'East Street Bakery',
            'stock_quantity': 5,
            'image': 'https://placehold.co/150',
            'allergens': ['Gluten', 'Sesame'],
            'is_available': True,
            'season_end': None,
        },
    ]

    # Filtering logic (which sidebar will do)

    # Get category from url
    category_query = request.GET.get('category') 

    if category_query:
        # Filter: Compare slug from URL to slug in our data
        display_products = [p for p in products if p['category'] == category_query]
    else:
        display_products = products

    # Context
    context = {
        'products': display_products,
        'categories': categories,
        'selected_category': category_query,
    }
    # Return Http response to user with filled context. (so they see the new filtered page).
    return render(request, 'marketplace/product_list.html', context)


def product_add(request):
    """Displays the Add Product form and handles front-end validation."""
    if request.method == 'POST': # If user submitted
        form = ProductAddForm(request.POST, request.FILES) # Files required to catch image upload.

        if form.is_valid():
            image_file = request.FILES.get('image')
            # Data validated at this point ready for CRUD API.
            print("Form is valid! Data received:")
            print(form.cleaned_data['name'])
            if image_file:
                print(f"Image File: {request.FILES['image'].name}")
            else:
                print("No image uploaded.")

            return redirect('marketplace:product_list') # After successful submission, redirect to product list page.
        
    else: # Viewing empty form (user opening page).
        form = ProductAddForm()
    
    return render(request, 'marketplace/product_form.html', {'form': form}) # Render product_form.html, pass form object
