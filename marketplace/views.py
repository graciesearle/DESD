from django.shortcuts import render, redirect
from products.models import Product
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

    # Pull all products from DB.
    products = Product.objects.all() 

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
