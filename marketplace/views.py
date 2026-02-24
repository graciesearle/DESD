from django.shortcuts import render, redirect
from products.models import Product
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q
from .models import Category
from .forms import ProductAddForm
from .serializers import ProductSerializer

def _get_active_products():
    """
    Returns QuerySet of products that are:
    1. Marked Available
    2. Currently in season. (Current date is within season_start and season_end (if set))
    """
    # Get todays date
    today = timezone.now().date()

    # Filter requirements:
    # - Must be marked available
    # - (Start date is not set OR start_date <= Today) AND
    # - (End date is not set OR end_date >= Today)
    
    return Product.objects.filter( # Q for complex queries
        Q(is_available=True) &
        (Q(season_start__isnull=True) | Q(season_start__lte=today)) &
        (Q(season_end__isnull=True) | Q(season_end__gte=today))
    )


# Create your views here.
def product_list(request):
    """
    Displays the marketplace (products) with sidebar filters.
    Includes Mock Data (until a model is built) to simulate database records.
    """

    # Fetch all categories from DB
    categories = Category.objects.all()


    # Pull all products (active and in season)
    products = _get_active_products()

    # Filtering logic (which sidebar will do)

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
    products = _get_active_products()
    
    # Filter by category if present in URL
    category_query = request.GET.get('category')
    if category_query:
        products = products.filter(category__slug=category_query)
    
    # Serialize data (basically convert DB objects into JSON)
    serializer = ProductSerializer(products, many=True) # Passing multiple products.

    return Response(serializer.data) # Returns JSON.