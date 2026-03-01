from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from products.models import Product
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Category
from .forms import ProductAddForm, FarmAddForm
from products.serializers import ProductSerializer

# Create your views here.
def product_list(request):
    """
    Displays the marketplace (products) with sidebar filters.
    Includes Mock Data (until a model is built) to simulate database records.
    """
    # Fetch all categories from DB
    categories = Category.objects.all()

    # Pull all products (active and in season)
    products = Product.objects.active_and_in_season()

    # Get category from url
    category_query = request.GET.get('category') 

    if category_query:
        # Filter: Compare slug from URL to slug in our db
        products = products.filter(category__slug=category_query)

    # Context
    context = {
        'products': products,
        'categories': categories,
        'selected_category': category_query,
    }
    # Return Http response to user with filled context. (so they see the new filtered page).
    return render(request, 'marketplace/product_list.html', context)

@login_required
def farm_add(request):
    if request.method == 'POST':
        form = FarmAddForm(request.POST)
        if form.is_valid():
            farm = form.save(commit=False)
            farm.producer = request.user # Auto-assign logged in user
            farm.save()
            # Redirect to Add Product Page now that they have a form.
            return redirect('marketplace:product_add')
    else:
        form = FarmAddForm()
    
    return render(request, 'marketplace/farm_form.html', {'form': form})

def product_add(request):
    """Displays the Add Product form and handles front-end validation."""
    if request.method == 'POST': # If user submitted
        form = ProductAddForm(request.POST, request.FILES) # Files required to catch image upload.

        if form.is_valid():
            image_file = request.FILES.get('image')
            # Data validated at this point ready for CRUD API. (CRUD API TASK SHOULD BE HERE)
            # --- START HERE ---
            print("Form is valid! Data received:")
            print(form.cleaned_data['name'])
            if image_file:
                print(f"Image File: {request.FILES['image'].name}")
            else:
                print("No image uploaded.")
            # --- END HERE ---
            return redirect('marketplace:product_list') # After successful submission, redirect to product list page.
        
    else: # Viewing empty form (user opening page).
        form = ProductAddForm()
    
    return render(request, 'marketplace/product_form.html', {'form': form}) # Render product_form.html, pass form object


@api_view(['GET']) # Only allows GET requests
def api_get_products(request):
    """
    API Endpoint: GET /marketplace/api/products/?category=x
    Returns JSON data using DRF.
    """
    # Get products
    products = Product.objects.active_and_in_season()
    
    # Filter by category if present in URL
    category_query = request.GET.get('category')
    if category_query:
        products = products.filter(category__slug=category_query)
    
    # Serialize data (basically convert DB objects into JSON)
    serializer = ProductSerializer(products, many=True) # Passing multiple products.

    return Response(serializer.data) # Returns JSON.