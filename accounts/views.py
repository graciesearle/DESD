from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q, Count, F
from django_ratelimit.decorators import ratelimit
from django.views.decorators.http import require_POST

from .forms import (
    UserUpdateForm, ProducerProfileUpdateForm, ProducerNotificationForm,
    CustomerProfileUpdateForm, CustomerPreferencesForm, ProducerRegistrationForm, 
    CustomerRegistrationForm, CustomAuthenticationForm, ProducerNotificationSettingsForm
)

from .decorators import producer_required
from marketplace.models import EducationalPost, Recipe
from products.forms import ProducerResponseForm
from products.models import Product, Review
from django.http import JsonResponse
from django.conf import settings
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

import logging
import requests
import stripe

logger = logging.getLogger(__name__)

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

    low_stock_items = products.filter(
        stock_quantity__lte=F('low_stock_threshold'),
        is_available=True
    )

    # Server-Side Filtering based on URL parameter
    status_filter = request.GET.get('status_filter', 'all')
    if status_filter == 'active':
        products = products.filter(is_available=True)
    elif status_filter == 'inactive':
        products = products.filter(is_available=False)

    educational_posts = EducationalPost.objects.active_posts().filter(producer=request.user)

    # Pagination (10 products per page)
    paginator = Paginator(products, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    today = timezone.localdate()

    if today.month == 12:
        next_month_1st = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month_1st = today.replace(month=today.month + 1, day=1)
        
    next_month_start = next_month_1st.strftime('%m-%d')

    upcoming_seasonal = Product.objects.filter(
        producer=request.user,
        is_year_round=False,
        is_deleted=False,
        season_start=next_month_start,
        producer__is_active=True,
        farm__is_deleted=False
    ).exclude(
        is_available=True # If active, it the red box problem (low stock)
    )

    context = {
        'products': page_obj,
        'low_stock_items': low_stock_items,
        'status_filter': status_filter,
        'educational_posts': educational_posts,
        'upcoming_seasonal': upcoming_seasonal,
        'next_month_name': next_month_1st.strftime('%B'),
        'recipes': Recipe.objects.filter(
            producer=request.user,
            is_deleted=False
        ).order_by('-created_at'),
        **stats,
    }
    return render(request, 'accounts/producer_dashboard.html', context)


@producer_required
def producer_reviews(request):
    """Inbox of reviews for the logged-in producer's products."""
    reviews = (
        Review.objects
        .filter(product__producer=request.user, is_deleted=False)
        .select_related('product', 'customer', 'customer__customer_profile')
        .order_by('-created_at')
    )

    response_filter = request.GET.get('response', 'all')
    if response_filter == 'pending':
        reviews = reviews.filter(producer_response='')
    elif response_filter == 'responded':
        reviews = reviews.exclude(producer_response='')

    paginator = Paginator(reviews, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'accounts/producer_reviews.html', {
        'reviews': page_obj.object_list,
        'page_obj': page_obj,
        'response_filter': response_filter,
    })


@producer_required
@require_POST
@ratelimit(key='user_or_ip', rate='30/h', block=True)
def producer_review_respond(request, review_id):
    """Submit or update a producer response to a product review."""
    review = get_object_or_404(
        Review.objects.select_related('product'),
        pk=review_id,
        product__producer=request.user,
        is_deleted=False,
    )

    form = ProducerResponseForm(request.POST, instance=review)
    if form.is_valid():
        updated_review = form.save(commit=False)
        updated_review.producer_responded_at = timezone.now()
        # Re-Trigger rule: reset response moderation so admins re-triage.
        updated_review.response_moderation_status = 'PENDING'
        updated_review.save(update_fields=[
            'producer_response', 'producer_responded_at',
            'response_moderation_status', 'updated_at',
        ])
        messages.success(request, f"Response saved for {review.product.name} review.")
    else:
        messages.error(request, "Could not save response. Please check the form and try again.")

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)

    return redirect('producer_reviews')

logger = logging.getLogger('accounts.security')

# Limit to 10 requests per minute, per ip address. Block if exceeded (for bots)
@ratelimit(key='ip', rate='10/m', block=True)
def producer_register(request):
    if request.method == "POST":
        form = ProducerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Log user in
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            # Security additions same as login.html
            # Force a 1-hour timeout since this page does not have a "remember me" box.
            request.session.set_expiry(3600)
            # Add to security audit log
            logger.info(f"New Producer registered and automatically logged in: {user.email}")

            messages.success(request, "Your producer account has been created successfully.")
            return redirect("producer_onboarding")
    else:
        form = ProducerRegistrationForm()

    return render(request, "accounts/producer_register.html", {"form": form})


# Limit to 10 requests per minute, per ip address. Block if exceeded (for bots)
@ratelimit(key='ip', rate='10/m', block=True)
def customer_register(request):
    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            request.session.set_expiry(3600)
            logger.info(f"New Producer registered and automatically logged in: {user.email}")
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


# ---- Settings Start: All the views below will be for different setting tabs. ----

@login_required
def settings_view(request):
    user = request.user
    active_tab = request.GET.get('tab', 'account')

    # Initialize forms for GET request
    user_form = UserUpdateForm(instance=user)
    password_form = PasswordChangeForm(user)
    
    # Conditional Form Initialization
    profile_form, notif_form, customer_form, pref_form = None, None, None, None
    stripe_requirements_due = False
    stripe_disabled_reason = None

    if user.is_producer and hasattr(user, 'producer_profile'):
        profile = user.producer_profile
        profile_form = ProducerProfileUpdateForm(instance=profile)
        notif_form = ProducerNotificationForm(instance=profile)
        
        # Check Stripe Verification Status
        if profile.stripe_account_id:
            try:
                stripe.api_key = settings.STRIPE_SECRET_KEY
                account = stripe.Account.retrieve(profile.stripe_account_id)
                # Flag as 'due' if there are currently due OR eventually due requirements
                # Or if payouts are not enabled.
                has_requirements = (
                    len(account.requirements.currently_due) > 0 or 
                    len(account.requirements.eventually_due) > 0
                )
                stripe_requirements_due = has_requirements or not account.payouts_enabled
                stripe_disabled_reason = account.requirements.disabled_reason
            except Exception as e:
                logger.error(f"Error fetching Stripe account status: {e}")

    elif user.is_customer and hasattr(user, 'customer_profile'):
        profile = user.customer_profile
        customer_form = CustomerProfileUpdateForm(instance=profile, user_role=user.role)
        pref_form = CustomerPreferencesForm(instance=profile)
    
    # Otherwise if user is admin they just get user form and password form
        
    if request.method == "POST":
        form_type = request.POST.get('form_type')
        active_tab = form_type # Keep them on the tab they just submitted

        if form_type == 'account':
            user_form = UserUpdateForm(request.POST, instance=user)
            if user_form.is_valid():
                user_form.save()
                messages.success(request, "Account details updated.")
                return redirect(f"{reverse('settings')}?tab=account")

        elif form_type == 'security':
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user) # Prevents logging them out
                messages.success(request, "Password successfully updated.")
                return redirect(f"{reverse('settings')}?tab=security")

        elif form_type == 'producer_profile' and user.is_producer:
            profile_form = ProducerProfileUpdateForm(request.POST, instance=profile)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Professional info updated.")
                return redirect(f"{reverse('settings')}?tab=producer_profile")

        elif form_type == 'producer_notif' and user.is_producer:
            notif_form = ProducerNotificationForm(request.POST, instance=profile)
            if notif_form.is_valid():
                notif_form.save()
                messages.success(request, "Notification preferences updated.")
                return redirect(f"{reverse('settings')}?tab=producer_notif")

        elif form_type == 'customer_profile' and user.is_customer:
            customer_form = CustomerProfileUpdateForm(request.POST, instance=profile, user_role=user.role)
            if customer_form.is_valid():
                customer_form.save()
                messages.success(request, "Delivery profile updated.")
                return redirect(f"{reverse('settings')}?tab=customer_profile")

        elif form_type == 'customer_pref' and user.is_customer:
            pref_form = CustomerPreferencesForm(request.POST, instance=profile)
            if pref_form.is_valid():
                pref_form.save()
                messages.success(request, "Preferences updated.")
                return redirect(f"{reverse('settings')}?tab=customer_pref")

    context = {
        'active_tab': active_tab,
        'user_form': user_form,
        'password_form': password_form,
        'profile_form': profile_form,
        'notif_form': notif_form,
        'customer_form': customer_form,
        'pref_form': pref_form,
        'stripe_requirements_due': stripe_requirements_due,
        'stripe_disabled_reason': stripe_disabled_reason,
    }
    return render(request, 'accounts/settings.html', context)


@login_required
def export_user_data(request):
    """Generates a JSON file containing the user's data (which can be for GDPR compliance)."""
    user = request.user
    data = {
        "account": {
            "email": user.email,
            "role": user.get_role_display(),
            "joined_date": user.date_joined,
            "phone": user.phone,
        }
    }
    
    if user.is_producer and hasattr(user, 'producer_profile'):
        p = user.producer_profile
        data["profile"] = {
            "business_name": p.business_name,
            "contact_name": p.contact_name,
            "address": p.address,
            "postcode": p.postcode,
            "bio": p.bio,
            "organic_certified": p.organic_certified,
            "tax_reference": p.tax_reference,
        }
    elif user.is_customer and hasattr(user, 'customer_profile'):
        c = user.customer_profile
        data["profile"] = {
            "full_name": c.full_name,
            "organisation_name": c.organisation_name,
            "delivery_address": c.delivery_address,
            "postcode": c.postcode,
        }
    # Admin only get base account info.

    response = JsonResponse(data, encoder=DjangoJSONEncoder, json_dumps_params={'indent': 4})
    response['Content-Disposition'] = f'attachment; filename="bristol_food_data.json"' # Download instead of display
    return response


@login_required
@require_POST
def deactivate_account(request):
    """Soft deletes the user so order history remains intact due to cascade relationship as well as maintaining trail history."""
    user = request.user
    user.is_active = False
    user.save()
    logout(request)
    messages.success(request, "Your account has been deactivated. Contact support to restore it.")
    return redirect('login')

@login_required
@require_POST
def remove_subscription(request, producer_id):
    if request.user.is_customer:
        try:
            from .models import ProducerProfile
            producer = ProducerProfile.objects.get(id=producer_id)
            request.user.customer_profile.subscribed_producers.remove(producer)
            messages.success(request, f"Unsubscribed from {producer.business_name}.")
        except ProducerProfile.DoesNotExist:
            pass
    return redirect(f"{reverse('settings')}?tab=customer_pref")

# ---- Settings End: All the views above will be for different setting tabs. ----

@producer_required
@require_POST
# Saves producer notification preferences for low stock emails.
def update_notification_settings(request):
    profile = request.user.producer_profile
    form = ProducerNotificationSettingsForm(request.POST, instance=profile)
    if form.is_valid():
        form.save()
        messages.success(request, "Notification preferences updated.")
    else:
        messages.error(request, "Could not save preferences.")
    return redirect('producer_dashboard')


@producer_required
def stripe_connect(request):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    profile = request.user.producer_profile
    
    try:
        if not profile.stripe_account_id:
            # Create a new connected account
            account = stripe.Account.create(
                type="express",
                country="GB",
                email=request.user.email,
                capabilities={
                    "transfers": {"requested": True},
                },
                business_type="individual",
            )
            profile.stripe_account_id = account.id
            profile.save()
        
        # Create an account link. 
        # Even if they already have an ID, this takes them back to the 
        # Stripe-hosted onboarding/verification flow.
        account_link = stripe.AccountLink.create(
            account=profile.stripe_account_id,
            refresh_url=request.build_absolute_uri(reverse('stripe_refresh')),
            return_url=request.build_absolute_uri(reverse('stripe_return')),
            type="account_onboarding",
            collection_options={
                "fields": "eventually_due",
            }
        )
        return redirect(account_link.url)
    except Exception as e:
        logger.error(f"Stripe connect error: {e}")
        messages.error(request, "Could not connect to Stripe. Please try again later.")
        return redirect(f"{reverse('settings')}?tab=producer_financial")

@producer_required
def stripe_return(request):
    # This is called when the producer completes the onboarding flow
    profile = request.user.producer_profile
    profile.stripe_onboarding_complete = True
    profile.save()
    messages.success(request, "Stripe account successfully linked!")
    return redirect(f"{reverse('settings')}?tab=producer_financial")

@producer_required
def stripe_refresh(request):
    # This is called if the link expires or the user goes back during onboarding
    messages.warning(request, "Stripe onboarding was interrupted. Please try again.")
    return redirect(f"{reverse('settings')}?tab=producer_financial")


@producer_required
def producer_onboarding(request):
    """Post-registration onboarding page to encourage Stripe connection."""
    # If they are already connected, just go to dashboard
    if request.user.producer_profile.stripe_onboarding_complete:
        return redirect("producer_dashboard")
    return render(request, "accounts/producer_onboarding.html")

