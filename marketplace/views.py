from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.db import transaction
from products.models import (
    Product,
    Farm,
    Allergen,
    Review,
    ProductBatch,
    default_discount_percent_for_grade,
    sync_product_stock_from_active_batches,
)
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Case, When, IntegerField
from django.http import JsonResponse
from django.urls import reverse
from .models import Category, EducationalPost
from .forms import ProductAddForm, FarmAddForm, EducationalPostForm
from products.serializers import ProductSerializer
from products.services.reviews import review_eligibility_for_product
from accounts.decorators import producer_required, customer_required
from accounts.models import ProducerProfile
from orders.models import Notification
from ai_engineering.models import BatchGradeChangeEvent


def _safe_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _get_allergen_dropdown_options():
    """Return allergen dropdown options sourced from the database."""
    options = [('', 'Select allergen')]
    db_options = list(
        Allergen.objects.order_by('name').values_list('name', 'name')
    )
    return options + db_options


def _apply_product_filters(queryset, category_query='', selected_allergen='', allergen_mode='', has_allergens=''):
    """Apply category/allergen filters to the product list queryset."""
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

    return queryset.distinct()

# Create your views here.
def product_detail(request, pk):
    """
    Displays a single product page with full details:
    image, description, price, allergens, farm origin,
    seasonal availability, stock, harvest date, and producer info.
    """
    product = get_object_or_404(
        Product.objects.select_related('category', 'producer', 'farm')
                       .prefetch_related('allergens', 'batches'),
        pk=pk,
        is_deleted=False,
    )
    active_batches = list(
        product.batches.filter(is_active=True, stock_quantity__gt=0).order_by('grade', 'created_at')
    )

    # Suggest related products from the same category (excluding current)
    related_products = (
        Product.objects.active_and_in_season()
        .filter(category=product.category)
        .exclude(pk=product.pk)[:4]
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
        'active_batches': active_batches,
        'has_active_batches': bool(active_batches),
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
    Includes Mock Data (until a model is built) to simulate database records.
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

    products = _apply_product_filters(
        products,
        category_query=category_query,
        selected_allergen=selected_allergen,
        allergen_mode=allergen_mode,
        has_allergens=has_allergens,
    )

    # Filter by specific producer if requested
    producer_query = request.GET.get('producer')
    if producer_query:
        products = products.filter(producer_id=producer_query)
    # Search query for products
    search_query = request.GET.get('q', '').strip()
    search_type = request.GET.get('search_type', 'products')

    if search_query:
        if search_type == 'farms':
            products = products.filter(
                Q(farm__name__icontains=search_query) |
                Q(producer__producer_profile__business_name__icontains=search_query)
            )
        else:  # products (default)
            products = products.filter(
                Q(name__icontains=search_query) |
                Q(description__icontains=search_query) |
                Q(producer__producer_profile__business_name__icontains=search_query)
            )

    # Context
    context = {
        'products': products,
        'categories': categories,
        'selected_category': category_query,
        'selected_allergen': selected_allergen,
        'allergen_mode': allergen_mode,
        'has_allergens': has_allergens,
        'allergen_dropdown_options': _get_allergen_dropdown_options(),
        'search_query': search_query,
        'search_type': search_type,
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
        start_batch_scan = request.POST.get('start_batch_scan') == '1'
        form = ProductAddForm(request.POST, request.FILES, user=request.user) # Files required to catch image upload.

        if form.is_valid():
            # Save product to database
            product = form.save(commit=False) 
            product.producer = request.user # Auto set the producer.
            product._change_reason = "Initial product creation"  # Give reason for history change.
            product.save()
            form.save_m2m() # Saves many to many fields like allergens.

            if start_batch_scan:
                messages.success(request, "Product saved. Continuing to AI batch scan.")
                edit_url = reverse('marketplace:product_edit', kwargs={'pk': product.pk})
                return redirect(f"{edit_url}?auto_ai_scan=1")

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
    category_query = request.GET.get('category', '')
    selected_allergen = request.GET.get('allergen', '').strip()
    allergen_mode = request.GET.get('allergen_mode', 'free')
    has_allergens = request.GET.get('has_allergens', '')

    products = _apply_product_filters(
        products,
        category_query=category_query,
        selected_allergen=selected_allergen,
        allergen_mode=allergen_mode,
        has_allergens=has_allergens,
    )
    
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
    product = get_object_or_404(
        Product.objects.prefetch_related("batches__grade_changes"),
        pk=pk,
        producer=request.user,
    )
    grade_batches = product.batches.filter(
        is_active=True,
        stock_quantity__gt=0,
    ).order_by('grade', 'created_at')
    auto_ai_scan_requested = request.GET.get('auto_ai_scan') == '1'
    has_active_grade_buckets = grade_batches.exists()
    unbatched_stock_quantity = int(product.unbatched_stock_quantity or 0)
    prefill_lot_quantity = (
        unbatched_stock_quantity
        if auto_ai_scan_requested and unbatched_stock_quantity > 0 and not has_active_grade_buckets
        else None
    )
    stock_managed_by_batches = product.batches.exists()

    if request.method == 'POST':
        form = ProductAddForm(
            request.POST, request.FILES,
            instance=product,
            user=request.user,
            lock_stock_quantity=stock_managed_by_batches,
        )
        if form.is_valid():
            updated_product = form.save(commit=False)
            updated_product._change_reason = "Updated product details via Dashboard"
            updated_product.save()
            form.save_m2m() # Restores many-to-many fields (like allergens) that are stripped by commit=False

            if updated_product.batches.exists():
                synced_total = sync_product_stock_from_active_batches(updated_product.id)
                messages.warning(
                    request,
                    (
                        "Stock quantity is managed by active grade buckets for this listing. "
                        f"Current stock has been aligned to {synced_total}."
                    ),
                )

            messages.success(request, f"'{updated_product.name}' updated successfully.")
            return redirect('marketplace:product_edit', pk=updated_product.pk)
    else:
        form = ProductAddForm(
            instance=product,
            user=request.user,
            lock_stock_quantity=stock_managed_by_batches,
        )

    return render(request, 'marketplace/product_form.html', {
        'form': form,
        'editing': True,
        'product': product,
        'grade_batches': grade_batches,
        'unbatched_stock_quantity': unbatched_stock_quantity,
        'prefill_lot_quantity': prefill_lot_quantity,
        'auto_ai_scan_requested': auto_ai_scan_requested,
        'stock_managed_by_batches': stock_managed_by_batches,
    })


@producer_required
@require_POST
def product_batch_toggle(request, batch_id):
    """Retire or reactivate a producer-owned product batch."""
    batch = get_object_or_404(
        ProductBatch.objects.select_related("product"),
        pk=batch_id,
        product__producer=request.user,
    )

    if not batch.is_active and batch.stock_quantity == 0:
        messages.warning(request, "Cannot activate a zero-stock batch. Increase stock first.")
        return redirect('marketplace:product_edit', pk=batch.product_id)

    if (
        not batch.is_active
        and ProductBatch.objects.filter(
            product_id=batch.product_id,
            grade=batch.grade,
            is_active=True,
        ).exclude(pk=batch.pk).exists()
    ):
        messages.warning(
            request,
            f"Grade {batch.grade} is already active for this listing. Use grade move instead.",
        )
        return redirect('marketplace:product_edit', pk=batch.product_id)

    batch.is_active = not batch.is_active
    batch.save(update_fields=["is_active"])

    action = "activated" if batch.is_active else "retired"
    messages.success(request, f"Grade {batch.grade} batch for '{batch.product.name}' has been {action}.")
    return redirect('marketplace:product_edit', pk=batch.product_id)


@producer_required
@require_POST
def product_batch_grade_edit(request, batch_id):
    """Manually update a batch grade from the product edit page."""
    with transaction.atomic():
        batch = get_object_or_404(
            ProductBatch.objects.select_for_update().select_related("product"),
            pk=batch_id,
            product__producer=request.user,
        )

        new_grade = (request.POST.get("new_grade") or "").strip().upper()
        reason = (request.POST.get("reason") or "").strip()

        valid_grades = {choice[0] for choice in ProductBatch.Grade.choices}
        if new_grade not in valid_grades:
            messages.error(request, "Please choose a valid grade (A, B, or C).")
            return redirect('marketplace:product_edit', pk=batch.product_id)

        if not reason:
            messages.error(request, "Please provide a reason for the grade change.")
            return redirect('marketplace:product_edit', pk=batch.product_id)

        if batch.grade == new_grade:
            messages.warning(request, "New grade matches the current grade. No change applied.")
            return redirect('marketplace:product_edit', pk=batch.product_id)

        old_grade = batch.grade
        target_batch = (
            ProductBatch.objects.select_for_update()
            .filter(product=batch.product, grade=new_grade)
            .exclude(pk=batch.pk)
            .order_by('-is_active', 'created_at')
            .first()
        )

        moved_quantity = int(batch.stock_quantity or 0)

        if target_batch:
            target_batch.base_price = batch.product.price
            target_batch.discount_percent = default_discount_percent_for_grade(new_grade)
            target_batch.stock_quantity = int(target_batch.stock_quantity) + moved_quantity
            target_batch.is_active = target_batch.stock_quantity > 0
            target_batch.save()

            batch.stock_quantity = 0
            batch.is_active = False
            batch.save()

            BatchGradeChangeEvent.objects.create(
                batch=target_batch,
                changed_by=request.user,
                old_grade=old_grade,
                new_grade=new_grade,
                reason=reason,
            )

            messages.success(
                request,
                f"Moved {moved_quantity} units from grade {old_grade} to {new_grade}.",
            )
        else:
            batch.grade = new_grade
            batch.base_price = batch.product.price
            batch.discount_percent = default_discount_percent_for_grade(new_grade)
            batch.is_active = batch.stock_quantity > 0
            batch.save()

            BatchGradeChangeEvent.objects.create(
                batch=batch,
                changed_by=request.user,
                old_grade=old_grade,
                new_grade=new_grade,
                reason=reason,
            )

            messages.success(
                request,
                f"Grade updated from {old_grade} to {new_grade}.",
            )

    return redirect('marketplace:product_edit', pk=batch.product_id)


@producer_required
@require_POST
def product_batch_stock_adjust(request, batch_id):
    """Subtract stock from a grade or move stock between grade buckets."""
    with transaction.atomic():
        source_batch = get_object_or_404(
            ProductBatch.objects.select_for_update().select_related('product'),
            pk=batch_id,
            product__producer=request.user,
        )

        product_id = source_batch.product_id
        action = (request.POST.get('action') or '').strip().lower()
        quantity = _safe_positive_int(request.POST.get('quantity'))
        reason = (request.POST.get('reason') or '').strip()

        if action not in {'subtract', 'move'}:
            messages.error(request, 'Please choose a valid stock action.')
            return redirect('marketplace:product_edit', pk=product_id)

        if quantity is None:
            messages.error(request, 'Quantity must be a whole number greater than 0.')
            return redirect('marketplace:product_edit', pk=product_id)

        if quantity > int(source_batch.stock_quantity):
            messages.error(
                request,
                f"Cannot adjust {quantity}. Grade {source_batch.grade} only has {source_batch.stock_quantity} units.",
            )
            return redirect('marketplace:product_edit', pk=product_id)

        if action == 'subtract':
            source_batch.stock_quantity = int(source_batch.stock_quantity) - quantity
            source_batch.base_price = source_batch.product.price
            source_batch.discount_percent = default_discount_percent_for_grade(source_batch.grade)
            source_batch.is_active = source_batch.stock_quantity > 0
            source_batch.save()

            detail = f"Removed {quantity} units from grade {source_batch.grade}."
            if reason:
                detail = f"{detail} Reason: {reason}"
            messages.success(request, detail)
            return redirect('marketplace:product_edit', pk=product_id)

        target_grade = (request.POST.get('target_grade') or '').strip().upper()
        valid_grades = {choice[0] for choice in ProductBatch.Grade.choices}
        if target_grade not in valid_grades:
            messages.error(request, 'Please choose a valid target grade (A, B, or C).')
            return redirect('marketplace:product_edit', pk=product_id)

        if target_grade == source_batch.grade:
            messages.error(request, 'Target grade must be different from source grade.')
            return redirect('marketplace:product_edit', pk=product_id)

        target_batch = (
            ProductBatch.objects.select_for_update()
            .filter(product=source_batch.product, grade=target_grade)
            .exclude(pk=source_batch.pk)
            .order_by('-is_active', 'created_at')
            .first()
        )
        if not target_batch:
            target_batch = ProductBatch.objects.create(
                product=source_batch.product,
                grade=target_grade,
                stock_quantity=0,
                base_price=source_batch.product.price,
                discount_percent=default_discount_percent_for_grade(target_grade),
                is_active=False,
            )

        source_grade = source_batch.grade

        source_batch.stock_quantity = int(source_batch.stock_quantity) - quantity
        source_batch.base_price = source_batch.product.price
        source_batch.discount_percent = default_discount_percent_for_grade(source_batch.grade)
        source_batch.is_active = source_batch.stock_quantity > 0
        source_batch.save()

        target_batch.stock_quantity = int(target_batch.stock_quantity) + quantity
        target_batch.base_price = source_batch.product.price
        target_batch.discount_percent = default_discount_percent_for_grade(target_grade)
        target_batch.is_active = target_batch.stock_quantity > 0
        target_batch.save()

        move_reason = reason or f"Moved {quantity} units from grade {source_grade} to {target_grade}."
        BatchGradeChangeEvent.objects.create(
            batch=target_batch,
            changed_by=request.user,
            old_grade=source_grade,
            new_grade=target_grade,
            reason=f"{move_reason} Quantity: {quantity}.",
        )

        messages.success(
            request,
            f"Moved {quantity} units from grade {source_grade} to {target_grade}.",
        )
        return redirect('marketplace:product_edit', pk=product_id)


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

    if search_type == 'farms':
        products = Product.objects.active_and_in_season().select_related('farm').filter(
            Q(farm__name__icontains=query) |
            Q(producer__producer_profile__business_name__icontains=query)
        ).order_by('farm__name').distinct('farm__name')[:5]

    else:
        products = Product.objects.active_and_in_season().select_related('producer__producer_profile').filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(producer__producer_profile__business_name__icontains=query)
        ).annotate(
            priority=Case(
                When(name__icontains=query, then=1),
                When(producer__producer_profile__business_name__icontains=query, then=2),
                When(description__icontains=query, then=3),
                default=4,
                output_field=IntegerField(),
            )
        ).order_by('priority')[:5]

    results = []
    for p in products:
        results.append({
            'id': p.pk,
            'name': p.farm.name if search_type == 'farms' and p.farm else p.name,
            'description': p.description[:60] + '...' if len(p.description) > 60 else p.description,
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
        form = EducationalPostForm(request.POST)
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
        form = EducationalPostForm(request.POST, instance=post)
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
    posts = EducationalPost.objects.active_posts().select_related('producer__producer_profile').annotate(
        num_likes=Count('likes')
    )
    
    # Sort by Likes first, then by Newest
    posts = posts.order_by('-num_likes', '-created_at')

    post_type = request.GET.get('type')
    if post_type:
        posts = posts.filter(post_type=post_type)
    
    # 10 posts per page
    paginator = Paginator(posts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Track which posts the current user has liked
    liked_post_ids = set()
    if request.user.is_authenticated:
        liked_post_ids = set(request.user.liked_posts.values_list('id', flat=True))


    return render(request, 'marketplace/community_feed.html', {
        'posts': page_obj.object_list,
        'page_obj': page_obj,
        'current_type': post_type,
        'liked_post_ids': liked_post_ids
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
