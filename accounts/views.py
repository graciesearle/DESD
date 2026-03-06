from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib import messages
from django.db.models import Q, Count

from .forms import ProducerRegistrationForm, CustomerRegistrationForm, CustomAuthenticationForm
from .decorators import producer_required
from products.models import Product
from django.http import JsonResponse
from django.conf import settings

from django.contrib.auth.views import LoginView
from django.contrib.auth import logout

import logging
import requests



@producer_required
def producer_dashboard(request):
    """
    Producer Product Dashboard (TC-003).

    Displays all products belonging to the authenticated producer,
    including both available and unavailable listings.  Provides
    summary counts so the producer can see their inventory at a glance.
    """
    products = (
        Product.objects
        .filter(producer=request.user)
        .select_related('category', 'farm')
        .order_by('-updated_at')
    )

    # Single query for all summary counts via conditional aggregation.
    stats = products.aggregate(
        total_count=Count('pk'),
        active_count=Count('pk', filter=Q(is_available=True)),
        inactive_count=Count('pk', filter=Q(is_available=False)),
        out_of_stock_count=Count('pk', filter=Q(stock_quantity=0)),
    )

    context = {
        'products': products,
        **stats,
    }
    return render(request, 'accounts/producer_dashboard.html', context)


def producer_register(request):
    if request.method == "POST":
        form = ProducerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, "Your producer account has been created successfully.")
            return redirect("producer_dashboard")
    else:
        form = ProducerRegistrationForm()

    return render(request, "accounts/producer_register.html", {"form": form})


def customer_register(request):
    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            messages.success(request, "Your customer account has been created successfully.")
            return redirect("marketplace:product_list")
    else:
        form = CustomerRegistrationForm()

    return render(request, "accounts/customer_register.html", {"form": form})


#address lookup
"""def address_search(request):
    query = request.GET.get("q")

    if not query:
        return JsonResponse({"results": []})

    try:
        response = requests.get(
            "https://portal.goaddress.io/api/address/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {settings.GO_ADDRESS_TOKEN}"},
            timeout=5
        )

        # temporary
        print("STATUS:", response.status_code)
        print("BODY:", response.text)
        print("TOKEN:", settings.GO_ADDRESS_TOKEN)

        if response.status_code != 200:
            return JsonResponse(
                {"error": "Address lookup failed"},
                status=response.status_code
            )
        return JsonResponse(response.json())

    except requests.RequestException as e:
        print("ERROR in address_search:", e)
        return JsonResponse({"error": str(e)}, status=500)"""
def address_search(request):
    q = request.GET.get('q')
    if not q:
        return JsonResponse({"error": "No postcode provided"}, status=400)

    url = f"https://portal.goaddress.io/api/address/search"
    headers = {"Authorization": f"Bearer {settings.GO_ADDRESS_TOKEN}",
                "Accept": "application/json"}
    params = {"q": q}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors
        data = response.json()
        return JsonResponse(data)

    except requests.RequestException as e:
        print("GO_ADDRESS_TOKEN:", settings.GO_ADDRESS_TOKEN)
        print("API response status:", response.status_code)
        print("API raw text:", response.text)
        print("RequestException:", e)
        return JsonResponse({"error": str(e)}, status=500)
    except ValueError as ve:
        print("JSON decode error:", ve)
        return JsonResponse({"error": "Invalid JSON from GoAddress"}, status=502)
    

logger = logging.getLogger('accounts.security')

class CustomLoginView(LoginView):
    form_class = CustomAuthenticationForm
    template_name = 'registration/login.html'

    def form_valid(self, form):
        remember_me = form.cleaned_data.get('remember_me')
        user = form.get_user()

        # Security logging
        logger.info(f"Successful login for user: {user.email}. Remember me: {remember_me}")

        response = super().form_valid(form) # logs user in and generates new session key.

        # Apply expiry rules to session created.
        if not remember_me:
            # Force a 1 hour timeout if "remember me" is not checked
            self.request.session.set_expiry(3600)
        else:
            # Session persists for set days
            self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        
        return response

    def form_invalid(self, form):
        username = self.request.POST.get('username', 'Unknown') # extracts what email user typed
        logger.warning(f"Failed login attempt for email: {username}")
        return super().form_invalid(form)
    
def custom_logout(request):
    """Secure logout ensuring session destruction."""
    if request.user.is_authenticated:
        logger.info(f"User logged out: {request.user.email}")
    logout(request)
    return redirect('login')