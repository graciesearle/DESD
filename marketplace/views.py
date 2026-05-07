from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from products.models import Product, Farm, Allergen, Review, SurplusDeal
from products.forms import SurplusDealForm
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib import messages
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank, SearchHeadline, TrigramSimilarity
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Case, When, IntegerField
from django.http import JsonResponse
from django.urls import reverse
from .models import Category, EducationalPost, Recipe, Comment
from .forms import ProductAddForm, FarmAddForm, EducationalPostForm, RecipeForm
from accounts.decorators import producer_required
from products.services.reviews import review_eligibility_for_product
from accounts.decorators import producer_required, customer_required
from accounts.models import ProducerProfile
from orders.models import Notification
from core.utils import calculate_food_miles
from itertools import chain
from operator import attrgetter
from datetime import timedelta
from django.utils import timezone


def _get_allergen_dropdown_options():
    """Return allergen dropdown options sourced from the database."""
    options = [('', 'Select allergen')]
    db_options = list(
        Allergen.objects.order_by('name').values_list('name', 'name')
    )
    return options + db_options


def _apply_product_filters(
    queryset,
    category_query='',
    selected_allergen='',
    allergen_mode='',
    has_allergens='',
    organic_filter='',
    show_surplus=False,
):
    """Apply category/allergen/organic filters to the product list queryset."""
    if category_query:
        queryset = queryset.filter(category__slug=category_query)

    if has_allergens == 'yes':
        queryset = queryset.filter(allergens__isnull=False)
    elif has_allergens == 'no':
        queryset = queryset.filter(allergens__isnull=True)

    if allergen_mode == 'contains' and selected_allergen:
        queryset = queryset.filter(allergens__name__icontains=selected_allergen)
    elif allergen_mode == 'free' and selected_allergen:
        queryset = queryset.exclude(allergens__name__icontains=selected_allergen)

    if organic_filter == 'certified':
        queryset = queryset.filter(organic_certificate__isnull=False)
    elif organic_filter == 'not_certified':
        queryset = queryset.filter(organic_certificate__isnull=True)
    
    if show_surplus:
        queryset = queryset.filter(
            surplus_deal__is_active=True,
            surplus_deal__surplus_quantity__gt=0,
            surplus_deal__expires_at__gt=timezone.now()
        )

    return queryset.distinct()


def _search(queryset, search_query, search_type):
    """
    Applies SearchVector: Extracts text from the specified columns -> splits sentences into individual words ->
                          removes stop words (e.g., "the" "and") -> converts remaining words into root words (lexemes) ->
                          maps lexeme positions -> tags lexemes with the weights assigned ->
                          Merges processed name + description into a vector.
    
    SearchQuery: Raw input string -> applies same series of rules to match the SearchVector format -> 
                 formats lexemes into logical query using OR logic (e.g., 'organ' | 'tomato')
                 so that results with any matching terms appear, but those will all terms rank higher.

    SearchRank: Checks if SearchQuery lexemes appear in the products SearchVector -> if they do, checks the tags
                (Weight A matches score higher than C) -> More appearance of a word and closer word proximity result in a higher score

    SearchHighlight: Generates a text snippet from the description, highlighting the matching terms with HTML <mark> tags.

    Handles two different modes 'farm' vs 'product'
    """
    if not search_query:
        return queryset
    
    words = search_query.split()
    combined_query = SearchQuery(words[0])
    for word in words[1:]:
        combined_query |= SearchQuery(word)
    
    if search_type == 'farms':
        vector = SearchVector('farm__name', weight='A') + SearchVector('producer__producer_profile__business_name', weight='B')
        sim_field = 'farm__name'
        sim_threshold = 0.2
        fallback_q = (
            Q(farm__name__icontains=search_query) |
            Q(producer__producer_profile__business_name__icontains=search_query) |
            Q(similarity__gt=sim_threshold) # stricter threshold for farm because they are usually shorter than product.
        )
    else:
        vector = SearchVector('name', weight='A') + SearchVector('producer__producer_profile__business_name', weight='B') + \
                 SearchVector('description', weight='C')
        sim_field = 'name'
        sim_threshold = 0.30
        fallback_q = (
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(producer__producer_profile__business_name__icontains=search_query) | 
            Q(similarity__gt=sim_threshold)
        )
    
    headline_config = {
        'start_sel': '<mark style="background-color: #FFFF00; padding: 0 2px; border-radius: 3px;">',
        'stop_sel': '</mark>'
    }
    # Phase 1: Full text search
    fts_qs = queryset.annotate(rank=SearchRank(vector, combined_query, cover_density=True), 
                               headline=SearchHeadline('description', combined_query, **headline_config)
                            ).filter(rank__gte=0.05).order_by('-rank')

    if fts_qs.exists():
        return fts_qs
    
    # Phase 2: Fallback typo tolerance
    return queryset.annotate(similarity=TrigramSimilarity(sim_field, search_query)).filter(fallback_q).order_by('-similarity', sim_field)

# Create your views here.
def product_detail(request, pk):
    """
    Displays a single product page with full details:
    image, description, price, allergens, farm origin,
    seasonal availability, stock, harvest date, and producer info.
    """
    product = get_object_or_404(
        Product.objects.select_related('category', 'producer', 'farm', 'organic_certificate')
                       .prefetch_related('allergens', 'recipes', 'featured_in_recipes__producer__producer_profile'),
        pk=pk,
        is_deleted=False,
    )

    # Suggest related products from the same category (excluding current)
    related_products = (
        Product.objects.active_and_in_season()
        .filter(category=product.category)
        .exclude(pk=product.pk)[:4]
    )

    if request.user.is_authenticated and hasattr(request.user, 'customer_profile'):
        if product.farm and product.farm.postcode:
            product.food_miles = calculate_food_miles(
                product.farm.postcode,
                request.user.customer_profile.postcode
            )

    visible_reviews = (
        Review.objects.filter(
            product=product,
            is_visible=True,
            is_deleted=False,
        )
        .select_related("customer", "customer__customer_profile")
        .order_by("-created_at")
    )
    rating_summary = visible_reviews.aggregate(
        review_count=Count("id"),
        average_rating=Avg("rating"),
    )
    average_rating = rating_summary["average_rating"] or 0

    customer_review_state = None
    if request.user.is_authenticated and getattr(request.user, "is_customer", False):
        eligibility = review_eligibility_for_product(user=request.user, product=product)

        add_review_url = None
        if eligibility.can_review and eligibility.order and eligibility.order_item_id:
            add_review_url = reverse(
                "orders:create_review",
                args=[eligibility.order.order_number, eligibility.order_item_id],
            )

        customer_review_state = {
            "previously_purchased": eligibility.previously_purchased,
            "can_add_review": eligibility.can_review,
            "code": eligibility.code,
            "message": eligibility.message,
            "add_review_url": add_review_url,
        }

    context = {
        'product': product,
        'related_products': related_products,
        'reviews': visible_reviews,
        'review_count': rating_summary["review_count"],
        'average_rating': round(float(average_rating), 1) if average_rating else 0,
        'customer_review_state': customer_review_state,
    }
    return render(request, 'marketplace/product_detail.html', context)


@customer_required
@require_POST
def delete_own_review(request, pk, review_id):
    """Allow a customer to soft-delete their own review from product detail."""
    review = get_object_or_404(
        Review,
        pk=review_id,
        product_id=pk,
        customer=request.user,
        is_deleted=False,
    )
    review.delete()
    messages.success(request, "Your review was deleted.")
    return redirect("marketplace:product_detail", pk=pk)


def product_list(request):
    """
    Displays the marketplace (products) with search bar and sidebar filters.
    """
    # Fetch all categories from DB
    categories = Category.objects.all()

    # Pull all products (active and in season)
    products = Product.objects.active_and_in_season()

    # Get category from url
    category_query = request.GET.get('category', '')
    selected_allergen = request.GET.get('allergen', '').strip()
    allergen_mode = request.GET.get('allergen_mode', 'free')
    has_allergens = request.GET.get('has_allergens', '')
    organic_filter = request.GET.get('organic', '').strip()

    products = _apply_product_filters(
        products,
        category_query=category_query,
        selected_allergen=selected_allergen,
        allergen_mode=allergen_mode,
        has_allergens=has_allergens,
        organic_filter=organic_filter,
    )

    # Surplus Deal filter
    show_surplus = request.GET.get('surplus', '') == 'true'
    if show_surplus:
        products = products.filter(
            surplus_deal__is_active=True,
            surplus_deal__surplus_quantity__gt=0,
            surplus_deal__expires_at__gt=timezone.now()
        ).order_by('surplus_deal__expires_at')

    # Filter by specific producer if requested
    producer_query = request.GET.get('producer')
    if producer_query:
        products = products.filter(producer_id=producer_query)
    # Search query for products
    search_query = request.GET.get('q', '').strip()
    search_type = request.GET.get('search_type', 'products')

    if search_query:
        products = _search(products, search_query, search_type)

    products_list = list(products)
    if request.user.is_authenticated and hasattr(request.user, 'customer_profile'):
        customer_postcode = request.user.customer_profile.postcode
        for p in products_list:
            if p.farm and p.farm.postcode:
                p.food_miles = calculate_food_miles(p.farm.postcode, customer_postcode)

    # Context
    context = {
        'products': products_list,
        'categories': categories,
        'selected_category': category_query,
        'selected_allergen': selected_allergen,
        'allergen_mode': allergen_mode,
        'has_allergens': has_allergens,
        'organic_filter': organic_filter,
        'allergen_dropdown_options': _get_allergen_dropdown_options(),
        'search_query': search_query,
        'search_type': search_type,
        'show_surplus': show_surplus,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'marketplace/_product_grid.html', context)

    # Full page render (initial load)
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
            product._change_reason = "Initial product creation"  # Give reason for history change.
            product.save()
            form.save_m2m() # Saves many to many fields like allergens.

            messages.success(request, "Product listed successfully!")
            return redirect('producer_dashboard')  # Keep producer in their management flow.
        
    else: # Viewing empty form (user opening page).
        form = ProductAddForm(user=request.user)
    
    return render(request, 'marketplace/product_form.html', {'form': form}) # Render product_form.html, pass form object

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
            updated_product = form.save(commit=False)
            updated_product._change_reason = "Updated product details via Dashboard"
            updated_product.save()
            form.save_m2m() # Restores many-to-many fields (like allergens) that are stripped by commit=False
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
    product._change_reason = "Marked as Available" if product.is_available else "Marked as Unavailable"
    product.save() # Removed update_fields=['is_available'] to ensure django-simple-history captures the save hook cleanly

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
    product._change_reason = "Soft-deleted product"
    product.delete()  # Soft-delete via SoftDeleteModel
    messages.success(request, f"'{product_name}' has been removed.")
    return redirect('producer_dashboard')

# Search bar drop down 
def search_suggestions(request):
    """
    API endpoint for live search dropdown suggestions.
    Returns top 5 matches prioritised by name first, then description.
    """
    query = request.GET.get('q', '').strip()
    search_type = request.GET.get('search_type', 'products')
    
    if len(query) < 2:
        return JsonResponse({'results': []})

    products = Product.objects.active_and_in_season()

    # Apply filters
    products = _apply_product_filters(
        products,
        category_query=request.GET.get('category', ''),
        selected_allergen=request.GET.get('allergen', '').strip(),
        allergen_mode=request.GET.get('allergen_mode', 'free'),
        organic_filter=request.GET.get('organic', '').strip(),
        show_surplus=(request.GET.get('surplus') == 'true')
    )

    products = _search(products, query, search_type)[:5]

    results = []
    for p in products:
        if hasattr(p, 'headline') and p.headline:
            desc = p.headline  
        else:
            desc = (p.description[:57] + '...') if p.description else ""
        results.append({
            'id': p.pk,
            'name': p.farm.name if search_type == 'farms' and p.farm else p.name,
            'description': desc,
            'price': str(p.price),
            'unit': p.unit,
            'url': reverse('marketplace:product_detail', kwargs={'pk': p.pk}),
            'image': p.image.url if p.image else None,
        })

    return JsonResponse({'results': results})

# HISTORY (Fetch history -> compare versions -> generate changes logic)

@producer_required
def product_history(request, pk):
    """
    Displays a vertical timeline of all changes made to a product.
    """
    product = get_object_or_404(Product, pk=pk, producer=request.user)

    history_records = product.history.all().order_by('-history_date')

    timeline = []
    for record in history_records:
        prev_record = record.prev_record
        changes = []

        # Calculate diff
        if prev_record:
            delta = record.diff_against(prev_record) # helper from django-simple-history
            for change in delta.changes:
                # Ignore background metadata
                if change.field not in ['updated_at', 'created_at', 'is_deleted', 'deleted_at']:
                    changes.append({
                        'field': change.field.replace('_', ' ').title(),
                        'old': str(change.old),
                        'new': str(change.new),
                    })
        
        # Determin badge color/action
        action_type = "Updated"
        if record.history_type == '+':
            action_type = "Created"
        elif record.history_type == '-':
            action_type = "Deleted" # For hard deletes
        elif record.is_deleted and prev_record and not prev_record.is_deleted:
            action_type = "Removed" # Soft deletes

        user_label = "System"
        if record.history_user:
            # Check for admins (so we dont expose their email)
            user = record.history_user
            if user.is_superuser or user.is_staff or getattr(user, 'is_admin', False):
                user_label = "System Admin"
            else:
                user_label = user.email

        timeline.append({
            'date': record.history_date,
            'user': user_label,
            'action': action_type,
            'reason': record.history_change_reason,
            'changes': changes
        })
    
    return render(request, 'marketplace/product_history.html', {
        'product': product,
        'timeline': timeline,
    })

# Post in Producer Dashboard
@producer_required
def create_educational_post(request):
    if request.method == 'POST':
        form = EducationalPostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.producer = request.user
            post.save()

            # Create notifications for subscribers (triggers emails automatically)
            if form.cleaned_data.get('send_email_alert'):
                subscribers = post.producer.producer_profile.subscribers.filter(
                    receive_educational_emails=True
                )
                for profile in subscribers:
                    Notification.objects.create(
                        recipient=profile.user,
                        notification_type=Notification.Type.NEW_POST,
                        educational_post=post,
                        message=f"{post.producer.producer_profile.business_name} posted a new {post.get_post_type_display()}: {post.title}"
                    )
            
            messages.success(request, "Post published successfully!")
            return redirect('producer_dashboard')
    else:
        form = EducationalPostForm()
    return render(request, 'marketplace/post_form.html', {'form': form})

@producer_required
def edit_educational_post(request, pk):
    post = get_object_or_404(EducationalPost, pk=pk, producer=request.user)
    
    if request.method == 'POST':
        form = EducationalPostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            updated_post = form.save(commit=False)
            updated_post._change_reason = "Updated post content"
            updated_post.save()
            messages.success(request, "Post updated successfully!")
            return redirect('producer_dashboard') 
    else:
        form = EducationalPostForm(instance=post)
        
    return render(request, 'marketplace/post_form.html', {'form': form, 'editing': True})

@producer_required
@require_POST
def delete_educational_post(request, pk):
    post = get_object_or_404(EducationalPost, pk=pk, producer=request.user)
    post._change_reason = "Soft-deleted post" # Producers likely wont see this, but just in case.
    post.delete() 
    messages.success(request, "Post removed successfully.")
    return redirect('producer_dashboard')

# Community Feed for customers
def community_feed(request):
    post_type = request.GET.get('type')

    posts = EducationalPost.objects.active_posts().select_related(
        'producer__producer_profile'
    ).annotate(
        num_likes=Count('likes')
    )

    # If filtering by a specific post type other than RECIPE,
    # only show that post type and no Recipe model items.
    if post_type and post_type != 'RECIPE':
        posts = posts.filter(post_type=post_type)

    # Recipe model items
    recipes = Recipe.objects.none()
    if not post_type or post_type == 'RECIPE':
        recipes = Recipe.objects.filter(
            is_published=True,
            is_deleted=False,
        ).select_related(
            'producer__producer_profile'
        ).prefetch_related(
            'linked_products'
        ).annotate(
            num_saves=Count('saved_by')
        ).order_by('-created_at')

    # If RECIPE is selected, also filter EducationalPost items to RECIPE
    if post_type == 'RECIPE':
        posts = posts.filter(post_type='RECIPE')

    # Tag each object so the template knows which type it is
    posts = list(posts)
    recipes = list(recipes)

    for p in posts:
        p.feed_type = 'post'
    for r in recipes:
        r.feed_type = 'recipe'

    # Merge and sort by date
    combined = sorted(
        chain(posts, recipes),
        key=attrgetter('created_at'),
        reverse=True
    )

    paginator = Paginator(combined, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    liked_post_ids = set()
    saved_recipe_ids = set()
    if request.user.is_authenticated:
        liked_post_ids = set(request.user.liked_posts.values_list('id', flat=True))
        saved_recipe_ids = set(request.user.saved_recipes.values_list('id', flat=True))

    post_comments = {}
    recipe_comments = {}

    post_ids = [item.pk for item in combined if getattr(item, 'feed_type', '') == 'post']
    recipe_ids = [item.pk for item in combined if getattr(item, 'feed_type', '') == 'recipe']

    if post_ids:
        all_post_comments = Comment.objects.filter(
            post_id__in=post_ids,
            parent=None,
            is_deleted=False
        ).select_related(
            'author__customer_profile',
            'author__producer_profile'
        ).prefetch_related('replies__author')
        for c in all_post_comments:
            post_comments.setdefault(c.post_id, []).append(c)

    if recipe_ids:
        all_recipe_comments = Comment.objects.filter(
            recipe_id__in=recipe_ids,
            parent=None,
            is_deleted=False
        ).select_related(
            'author__customer_profile',
            'author__producer_profile'
        ).prefetch_related('replies__author')
        for c in all_recipe_comments:
            recipe_comments.setdefault(c.recipe_id, []).append(c)
            
    return render(request, 'marketplace/community_feed.html', {
        'posts': page_obj.object_list,
        'page_obj': page_obj,
        'current_type': post_type,
        'liked_post_ids': liked_post_ids,
        'saved_recipe_ids': saved_recipe_ids,
        'post_comments': post_comments,
        'recipe_comments': recipe_comments,
    })

# "Meet the Producers" page for customers to subscribe
def producer_directory(request):
    producers = ProducerProfile.objects.select_related('user').filter(user__is_active=True).annotate(
        num_subscribers=Count('subscribers')
    )
    
    # Get IDs of producers the current user is subscribed to
    subscribed_ids = set()
    if request.user.is_authenticated and hasattr(request.user, 'customer_profile'):
        subscribed_ids = set(request.user.customer_profile.subscribed_producers.values_list('id', flat=True))

    return render(request, 'marketplace/producer_directory.html', {
        'producers': producers,
        'subscribed_ids': subscribed_ids
    })

@customer_required
@require_POST
def toggle_post_like(request, post_id):
    post = get_object_or_404(EducationalPost, id=post_id)
    if request.user in post.likes.all():
        post.likes.remove(request.user)
        is_liked = False
    else:
        post.likes.add(request.user)
        is_liked = True
    
    return JsonResponse({
        'is_liked': is_liked,
        'total_likes': post.likes.count()
    })

# "Subscribe button" for customers 
@customer_required
@require_POST
def toggle_subscription(request, producer_id):
    producer_profile = get_object_or_404(ProducerProfile, id=producer_id)
    customer_profile = request.user.customer_profile
    
    if producer_profile in customer_profile.subscribed_producers.all():
        customer_profile.subscribed_producers.remove(producer_profile)
        is_subscribed = False
    else:
        customer_profile.subscribed_producers.add(producer_profile)
        is_subscribed = True
        
    return JsonResponse({
        'is_subscribed': is_subscribed,
        'new_count': producer_profile.subscribers.count()
    })

# Recipes page for creating, editing, deleting, and viewing.
@producer_required
def create_recipe(request):
    """
    Producers can create and publish recipes linked to their products.
    Mirrors create_educational_post pattern.
    """
    if request.method == 'POST':
        form = RecipeForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            recipe = form.save(commit=False)
            recipe.producer = request.user
            recipe._change_reason = "Recipe created"
            recipe.save()
            form.save_m2m() 

            # Notify subscribers if requested
            if form.cleaned_data.get('send_email_alert') and recipe.is_published:
                subscribers = recipe.producer.producer_profile.subscribers.filter(
                    receive_educational_emails=True
                )
                for profile in subscribers:
                    Notification.objects.create(
                        recipient=profile.user,
                        notification_type=Notification.Type.NEW_POST,
                        message=f"{recipe.producer.producer_profile.business_name} shared a new recipe: {recipe.title}"
                    )

            messages.success(request, "Recipe created successfully!")
            return redirect('producer_dashboard')
    else:
        form = RecipeForm(user=request.user)

    return render(request, 'marketplace/recipe_form.html', {'form': form})


@producer_required
def edit_recipe(request, pk):
    """
    Producers can edit their own recipes.
    Mirrors edit_educational_post pattern.
    """
    recipe = get_object_or_404(Recipe, pk=pk, producer=request.user, is_deleted=False)

    if request.method == 'POST':
        form = RecipeForm(request.POST, request.FILES, instance=recipe, user=request.user)
        if form.is_valid():
            updated_recipe = form.save(commit=False)
            updated_recipe._change_reason = "Recipe updated"
            updated_recipe.save()
            form.save_m2m()
            messages.success(request, "Recipe updated successfully!")
            return redirect('producer_dashboard')
    else:
        form = RecipeForm(instance=recipe, user=request.user)

    return render(request, 'marketplace/recipe_form.html', {'form': form, 'editing': True})


@producer_required
@require_POST
def delete_recipe(request, pk):
    """
    Producers can remove their recipes. Soft delete to preserve history.
    Mirrors delete_educational_post pattern.
    """
    recipe = get_object_or_404(Recipe, pk=pk, producer=request.user, is_deleted=False)
    recipe._change_reason = "Recipe deleted by producer"
    recipe.delete()
    messages.success(request, "Recipe removed successfully.")
    return redirect('producer_dashboard')


def recipe_detail(request, pk):
    """Public recipe detail page. Customers click through from product pages.
    Linked products are shown with purchase links."""
    recipe = get_object_or_404(
        Recipe.objects.select_related('producer__producer_profile')
                      .prefetch_related('linked_products', 'featured_products__producer__producer_profile', 'comments__author__customer_profile', 'comments__replies__author'),
        pk=pk,
        is_published=True,
        is_deleted=False,
    )

    comments = recipe.comments.filter(
        parent=None,
        is_deleted=False
    ).prefetch_related('replies')

    return render(request, 'marketplace/recipe_details.html', {'recipe': recipe, 'comments': comments,})

@customer_required
@require_POST
def toggle_saved_recipe(request, pk):
    """Customers can save/unsave favourite recipes."""
    recipe = get_object_or_404(Recipe, pk=pk, is_published=True, is_deleted=False)

    if request.user in recipe.saved_by.all():
        recipe.saved_by.remove(request.user)
        is_saved = False
    else:
        recipe.saved_by.add(request.user)
        is_saved = True

    return JsonResponse({
        'is_saved': is_saved,
        'total_saves': recipe.saved_by.count()
    })

@login_required
@require_POST
def add_post_comment(request, post_id):
    post = get_object_or_404(EducationalPost, pk=post_id, is_deleted=False)
    body = request.POST.get('body', '').strip()

    if not body:
        messages.error(request, "Comment cannot be empty. Please insert your comment. ")
        return redirect(f"{reverse('marketplace:community_feed')}#post-{post_id}")

    Comment.objects.create(
        post=post,
        author=request.user,
        body=body,
    )
    messages.success(request, "Comment added.")
    return redirect(f"{reverse('marketplace:community_feed')}#post-{post_id}")


@login_required
@require_POST
def add_recipe_comment(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk, is_published=True, is_deleted=False)
    body = request.POST.get('body', '').strip()
    next_url = request.POST.get('next')

    if not body:
        messages.error(request, "Comment cannot be empty. Please insert your comment.")
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('marketplace:recipe_detail', pk=pk)

    Comment.objects.create(
        recipe=recipe,
        author=request.user,
        body=body,
    )
    messages.success(request, "Comment added.")

    if next_url and next_url.startswith('/'):
        return redirect(next_url)

    return redirect('marketplace:recipe_detail', pk=pk)

# ---------------------------------------------------------------------------
# Surplus Deals — Producer and Customer views
# ---------------------------------------------------------------------------

@producer_required
def mark_as_surplus(request, pk):
    """
    Allows a producer to create a surplus / last-minute deal on one of their products.
    GET: shows the surplus deal form with product info.
    POST: creates the SurplusDeal and notifies subscribed customers.
    """
    product = get_object_or_404(Product, pk=pk, producer=request.user, is_deleted=False)

    # Check if there is already an active deal
    existing_deal = SurplusDeal.objects.filter(product=product).first()
    if existing_deal:
        messages.warning(request, f"'{product.name}' already has an active surplus deal. Remove it first to create a new one.")
        return redirect('producer_dashboard')

    if request.method == 'POST':
        form = SurplusDealForm(request.POST, product=product)
        if form.is_valid():
            expiry_hours = form.cleaned_data['expiry_hours']
            surplus_quantity = form.cleaned_data['surplus_quantity']
            best_before_date = form.cleaned_data['best_before_date']
            deal = SurplusDeal(
                product=product,
                discount_percentage=form.cleaned_data['discount_percentage'],
                note=form.cleaned_data.get('note', ''),
                best_before_date=best_before_date,
                expires_at=timezone.now() + timedelta(hours=expiry_hours),
                surplus_quantity=surplus_quantity,
            )
            deal.save()
            

            # Notify subscribed customers who have opted in for surplus alerts
            try:
                producer_name = request.user.producer_profile.business_name
            except Exception:
                producer_name = request.user.email

            subscribers = request.user.producer_profile.subscribers.filter(
                receive_surplus_alerts=True
            )
            for profile in subscribers:
                Notification.objects.create(
                    recipient=profile.user,
                    notification_type=Notification.Type.SURPLUS_DEAL,
                    product=product,
                    message=(
                        f"{producer_name} has a last-minute deal: "
                        f"{deal.discount_percentage}% off {product.name} "
                        f"(now £{deal.discounted_price}/{product.unit}). "
                        f"Available for {expiry_hours} hours or until {surplus_quantity} items are sold!"
                    ),
                )

            messages.success(
                request,
                f"Surplus deal created: {deal.discount_percentage}% off '{product.name}'. "
                f"Deal expires in {expiry_hours} hours or when {surplus_quantity} items are sold."
            )
            return redirect('producer_dashboard')
    else:
        form = SurplusDealForm(
            initial={'discount_percentage': 30, 'expiry_hours': 48, 'surplus_quantity': product.stock_quantity},
            product=product
        )

    return render(request, 'marketplace/surplus_form.html', {
        'form': form,
        'product': product,
    })

@producer_required
@require_POST
def reply_to_comment(request, comment_id):
    """Producers can reply to a comment on their own post or recipe."""
    parent = get_object_or_404(Comment, pk=comment_id, is_deleted=False)
    body = request.POST.get('body', '').strip()
    next_url = request.POST.get('next')

    # Only the producer who owns the post/recipe can reply
    if parent.post and parent.post.producer != request.user:
        messages.error(request, "You can only reply to comments on your own posts.")
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('marketplace:community_feed')

    if parent.recipe and parent.recipe.producer != request.user:
        messages.error(request, "You can only reply to comments on your own recipes.")
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('marketplace:community_feed')

    if not body:
        messages.error(request, "Reply cannot be empty. Please insert your reply.")
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        if parent.recipe:
            return redirect('marketplace:recipe_detail', pk=parent.recipe.pk)
        return redirect(f"{reverse('marketplace:community_feed')}#post-{parent.post.pk}")

    existing_reply = Comment.objects.filter(
        parent=parent,
        author=request.user,
        is_deleted=False,
    ).first()

    if existing_reply:
        existing_reply.body = body
        existing_reply.save()
        messages.success(request, "Reply updated.")
    else:
        Comment.objects.create(
            post=parent.post,
            recipe=parent.recipe,
            author=request.user,
            parent=parent,
            body=body,
        )
        messages.success(request, "Reply added.")

    if next_url and next_url.startswith('/'):
        return redirect(next_url)

    if parent.recipe:
        return redirect('marketplace:recipe_detail', pk=parent.recipe.pk)
    return redirect(f"{reverse('marketplace:community_feed')}#post-{parent.post.pk}")

@login_required
@require_POST
def delete_comment(request, comment_id):
    """Authors and producers can delete comments."""
    comment = get_object_or_404(Comment, pk=comment_id, is_deleted=False)
    next_url = request.POST.get('next')

    is_author = comment.author == request.user
    is_content_owner = (
        (comment.post and comment.post.producer == request.user) or
        (comment.recipe and comment.recipe.producer == request.user)
    )

    if not (is_author or is_content_owner):
        messages.error(request, "You don't have permission to delete this comment.")
        if next_url and next_url.startswith('/'):
            return redirect(next_url)
        return redirect('marketplace:community_feed')

    recipe_pk = comment.recipe.pk if comment.recipe else None
    post_pk = comment.post.pk if comment.post else None

    comment.delete()
    messages.success(request, "Comment deleted.")

    if next_url and next_url.startswith('/'):
        return redirect(next_url)

    if recipe_pk:
        return redirect('marketplace:recipe_detail', pk=recipe_pk)
    return redirect(f"{reverse('marketplace:community_feed')}#post-{post_pk}")

def remove_surplus(request, pk):
    """
    Allows a producer to remove a surplus deal from their product.
    Used when stock sells out or the producer decides to end the deal.
    """
    product = get_object_or_404(Product, pk=pk, producer=request.user, is_deleted=False)
    try:
        deal = product.surplus_deal
        deal.delete()
        messages.success(request, f"Surplus deal removed from '{product.name}'.")
    except SurplusDeal.DoesNotExist:
        messages.warning(request, f"'{product.name}' has no active surplus deal.")

    return redirect('producer_dashboard')

def producer_profile(request, producer_id):
    profile = get_object_or_404(
        ProducerProfile.objects.select_related('user'),
        user_id=producer_id,
    )

    # Fetch farms through the user, not the profile
    farms = Farm.objects.filter(producer=profile.user)
    posts = EducationalPost.objects.active_posts().filter(producer=profile.user).order_by('-created_at')
    recipes = Recipe.objects.filter(producer=profile.user, is_published=True, is_deleted=False).order_by('-created_at')
    products = Product.objects.active_and_in_season().filter(producer=profile.user)[:8]

    is_subscribed = False
    if request.user.is_authenticated and hasattr(request.user, 'customer_profile'):
        is_subscribed = profile in request.user.customer_profile.subscribed_producers.all()

    return render(request, 'marketplace/producer_profile.html', {
        'producer': profile,
        'farms': farms,
        'posts': posts,
        'recipes': recipes,
        'products': products,
        'is_subscribed': is_subscribed,
    })