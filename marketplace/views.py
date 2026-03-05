from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from products.models import Product, Farm
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib import messages
from django.urls import reverse
from .models import Category
from .forms import ProductAddForm, FarmAddForm
from products.serializers import ProductSerializer
from accounts.decorators import producer_required

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

@producer_required
def farm_add(request):
    # Capture the "next" parameter from the URL if it exists.
    next_url = request.GET.get('next')

    if request.method == 'POST':
        form = FarmAddForm(request.POST, user=request.user)
        if form.is_valid():
            farm = form.save(commit=False)
            farm.producer = request.user # Auto-assign logged in user
            farm.save()

            messages.success(request, f"Farm '{farm.name}' registered successfully!")

            # Smart Redirect: Go back to where they came from, or default to product_list
            redirect_to = request.POST.get('next') # Get from Form submission as it disappears from url after submission
            if redirect_to and redirect_to.startswith('/'): # Security check (ensuring only internal urls are allowed)
                return redirect(redirect_to)
            return redirect('marketplace:product_add')
    else:
        form = FarmAddForm(user=request.user)
    
    return render(request, 'marketplace/farm_form.html', {'form': form, 'next': next_url}) # pass next_url to template as hidden form input.

@producer_required
def product_add(request):
    """Displays the Add Product form and handles front-end validation."""
    # Redirect if they have NO farms registered.
    if not Farm.objects.filter(producer=request.user).exists():
        messages.warning(request, "You must register at least one farm location before you can list a product.")
        # Redirect to farm form, but tell it to come back here afterwards.
        return redirect(f"{reverse('marketplace:farm_add')}?next={request.path}")
    
    if request.method == 'POST': # If user submitted (pass user to form so it knows what farms to allow)
        form = ProductAddForm(request.POST, request.FILES, user=request.user) # Files required to catch image upload.

        if form.is_valid():
            # Save product to database
            product = form.save(commit=False) 
            product.producer = request.user # Auto set the producer.
            product.save()
            form.save_m2m() # Saves many to many fields like allergens.

            messages.success(request, "Product listed successfully!")
            return redirect('producer_dashboard')  # Keep producer in their management flow.
        
    else: # Viewing empty form (user opening page).
        form = ProductAddForm(user=request.user)
    
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


# ---------------------------------------------------------------------------
# Producer product management views
# ---------------------------------------------------------------------------

@producer_required
def product_edit(request, pk):
    """
    Edit an existing product listing.

    Only the owning producer may edit the product — enforced by the
    queryset filter on ``producer=request.user``.  Reuses the same
    ``ProductAddForm`` and ``product_form.html`` template as the add
    flow, passing an ``editing`` flag so the template can adjust its
    heading and button label.
    """
    product = get_object_or_404(Product, pk=pk, producer=request.user)

    if request.method == 'POST':
        form = ProductAddForm(
            request.POST, request.FILES,
            instance=product, user=request.user,
        )
        if form.is_valid():
            updated_product = form.save()
            messages.success(request, f"'{updated_product.name}' updated successfully.")
            return redirect('producer_dashboard')
    else:
        form = ProductAddForm(instance=product, user=request.user)

    return render(request, 'marketplace/product_form.html', {
        'form': form,
        'editing': True,
        'product': product,
    })


@producer_required
@require_POST
def product_toggle(request, pk):
    """
    Toggle a product's ``is_available`` flag.

    POST-only to prevent accidental state changes from crawlers or
    bookmark links.  Redirects back to the producer dashboard.
    """
    product = get_object_or_404(Product, pk=pk, producer=request.user)
    product.is_available = not product.is_available
    product.save(update_fields=['is_available'])

    status = 'activated' if product.is_available else 'deactivated'
    messages.success(request, f"'{product.name}' has been {status}.")
    return redirect('producer_dashboard')


@producer_required
@require_POST
def product_delete(request, pk):
    """
    Soft-delete a product listing.

    Uses the ``SoftDeleteModel.delete()`` method so the record is
    retained for audit purposes while being hidden from normal queries.
    """
    product = get_object_or_404(Product, pk=pk, producer=request.user)
    product_name = product.name
    product.delete()  # Soft-delete via SoftDeleteModel
    messages.success(request, f"'{product_name}' has been removed.")
    return redirect('producer_dashboard')