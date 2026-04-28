"""
Admin Review Moderation Dashboard views.

Provides the admin-facing moderation queue for customer reviews and
producer responses, with filtering, search, bulk actions, and a
detail/history modal endpoint.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib import messages

from accounts.decorators import admin_required
from products.models import Review, ModerationStatus


# ── Helpers ──────────────────────────────────────────────────────────
def _get_producer_display(review):
    """Return a display name for the producer who owns the reviewed product."""
    try:
        return review.product.producer.producer_profile.business_name
    except AttributeError:
        return review.product.producer.email if review.product else "—"


# ── Main dashboard view ─────────────────────────────────────────────

@admin_required
def admin_review_moderation(request):
    """
    Consolidated moderation queue for reviews and producer responses.

    Default view: "Action Required" — items where review OR response
    moderation_status is PENDING.
    """
    from django.shortcuts import render

    reviews = (
        Review.all_objects
        .filter(is_deleted=False)
        .select_related(
            "product", "product__producer", "product__producer__producer_profile",
            "customer", "customer__customer_profile",
            "moderated_by", "response_moderated_by",
        )
    )

    # ── Filters ──────────────────────────────────────────────────
    status_filter = request.GET.get("status", "action_required")
    role_filter = request.GET.get("role", "")
    producer_filter = request.GET.get("producer", "")
    search_query = request.GET.get("q", "").strip()
    sort_by = request.GET.get("sort", "newest")

    if status_filter == "action_required":
        # Default: show reviews or responses that need admin attention
        reviews = reviews.filter(
            Q(moderation_status=ModerationStatus.PENDING)
            | Q(response_moderation_status=ModerationStatus.PENDING,
                producer_response__gt="")
        )
    elif status_filter in ModerationStatus.values:
        reviews = reviews.filter(moderation_status=status_filter)

    if role_filter:
        reviews = reviews.filter(customer__role=role_filter)

    if producer_filter and producer_filter.isdigit():
        reviews = reviews.filter(product__producer_id=producer_filter)

    if search_query:
        reviews = reviews.filter(
            Q(title__icontains=search_query)
            | Q(body__icontains=search_query)
            | Q(producer_response__icontains=search_query)
            | Q(customer__email__icontains=search_query)
            | Q(product__name__icontains=search_query)
        )

    # ── Sorting ──────────────────────────────────────────────────
    if sort_by == "oldest":
        reviews = reviews.order_by("created_at")
    elif sort_by == "rating_high":
        reviews = reviews.order_by("-rating", "-created_at")
    elif sort_by == "rating_low":
        reviews = reviews.order_by("rating", "-created_at")
    elif sort_by == "last_moderated":
        reviews = reviews.order_by("-moderated_at")
    else:  # newest (default)
        reviews = reviews.order_by("-created_at")

    # ── Pagination ───────────────────────────────────────────────
    paginator = Paginator(reviews, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Build query string for pagination links (strip "page" param)
    params = request.GET.copy()
    params.pop("page", None)
    base_query = params.urlencode()

    # ── Summary counts ───────────────────────────────────────────
    all_reviews = Review.all_objects.filter(is_deleted=False)
    pending_reviews = all_reviews.filter(moderation_status=ModerationStatus.PENDING).count()
    pending_responses = (
        all_reviews
        .filter(response_moderation_status=ModerationStatus.PENDING, producer_response__gt="")
        .count()
    )

    # ── Producers for filter dropdown ────────────────────────────
    from accounts.models import CustomUser
    producer_ids = (
        Review.all_objects.filter(is_deleted=False)
        .values_list("product__producer_id", flat=True)
        .distinct()
    )
    producers = (
        CustomUser.objects
        .filter(id__in=producer_ids, role="PRODUCER")
        .select_related("producer_profile")
        .order_by("email")
    )

    context = {
        "reviews": page_obj.object_list,
        "page_obj": page_obj,
        "base_query": base_query,
        "status_filter": status_filter,
        "role_filter": role_filter,
        "producer_filter": producer_filter,
        "search_query": search_query,
        "sort_by": sort_by,
        "pending_reviews": pending_reviews,
        "pending_responses": pending_responses,
        "producers": producers,
        "moderation_statuses": ModerationStatus.choices,
        "customer_roles": [
            ("CUSTOMER", "Individual"),
            ("COMMUNITY_GROUP", "Community Group"),
            ("RESTAURANT", "Restaurant"),
        ],
    }

    return render(request, "marketplace/admin_review_moderation.html", context)


# ── Single-review actions (AJAX-friendly) ────────────────────────────

@admin_required
@require_POST
def admin_moderate_review(request, review_id):
    """Change the moderation_status of a single review."""
    review = get_object_or_404(Review.all_objects, pk=review_id, is_deleted=False)
    action = request.POST.get("action")  # approve | reject
    reason = request.POST.get("reason", "").strip()

    if action == "approve":
        review.moderation_status = ModerationStatus.APPROVED
        review.moderation_reason = ""
    elif action == "reject":
        review.moderation_status = ModerationStatus.REJECTED
        review.moderation_reason = reason
    else:
        messages.error(request, "Invalid moderation action.")
        return redirect("marketplace:admin_review_moderation")

    review.moderated_by = request.user
    review.moderated_at = timezone.now()
    review.save(update_fields=[
        "moderation_status", "moderation_reason",
        "moderated_by", "moderated_at", "updated_at",
    ])

    label = "approved" if action == "approve" else "rejected"
    messages.success(request, f"Review by {review.customer.email} has been {label}.")
    return redirect("marketplace:admin_review_moderation")


@admin_required
@require_POST
def admin_moderate_response(request, review_id):
    """Change the response_moderation_status of a producer reply."""
    review = get_object_or_404(Review.all_objects, pk=review_id, is_deleted=False)
    action = request.POST.get("action")  # approve | reject

    if action == "approve":
        review.response_moderation_status = ModerationStatus.APPROVED
    elif action == "reject":
        review.response_moderation_status = ModerationStatus.REJECTED
    else:
        messages.error(request, "Invalid moderation action.")
        return redirect("marketplace:admin_review_moderation")

    review.response_moderated_by = request.user
    review.response_moderated_at = timezone.now()
    review.save(update_fields=[
        "response_moderation_status",
        "response_moderated_by", "response_moderated_at", "updated_at",
    ])

    label = "approved" if action == "approve" else "rejected"
    messages.success(request, f"Producer response on '{review.product.name}' has been {label}.")
    return redirect("marketplace:admin_review_moderation")


# ── Bulk actions ─────────────────────────────────────────────────────

@admin_required
@require_POST
def admin_bulk_moderate(request):
    """Bulk approve or reject selected reviews."""
    action = request.POST.get("bulk_action")  # bulk_approve | bulk_reject
    review_ids = request.POST.getlist("review_ids")

    if not review_ids:
        messages.warning(request, "No reviews selected.")
        return redirect("marketplace:admin_review_moderation")

    qs = Review.all_objects.filter(pk__in=review_ids, is_deleted=False)

    if action == "bulk_approve":
        qs.update(
            moderation_status=ModerationStatus.APPROVED,
            moderation_reason="",
            moderated_by=request.user,
            moderated_at=timezone.now(),
        )
        messages.success(request, f"{len(review_ids)} review(s) approved.")
    elif action == "bulk_reject":
        qs.update(
            moderation_status=ModerationStatus.REJECTED,
            moderated_by=request.user,
            moderated_at=timezone.now(),
        )
        messages.success(request, f"{len(review_ids)} review(s) rejected.")
    else:
        messages.error(request, "Invalid bulk action.")

    return redirect("marketplace:admin_review_moderation")


# ── Detail / History endpoint (for modal) ────────────────────────────

@admin_required
def admin_review_detail(request, review_id):
    """Return JSON with full review details and history for the modal."""
    review = get_object_or_404(
        Review.all_objects.select_related(
            "product", "product__producer__producer_profile",
            "customer", "customer__customer_profile",
            "moderated_by", "response_moderated_by",
        ),
        pk=review_id,
        is_deleted=False,
    )

    # Build history from django-simple-history
    history = []
    for record in review.history.all().order_by("-history_date")[:20]:
        history.append({
            "date": record.history_date.strftime("%d %b %Y %H:%M"),
            "user": str(record.history_user or "System"),
            "reason": record.history_change_reason or "—",
            "type": record.history_type,
        })

    producer_name = _get_producer_display(review)

    data = {
        "id": review.id,
        "product_name": review.product.name if review.product else "Archived Product",
        "product_id": review.product_id,
        "product_image": review.product.image.url if review.product and review.product.image else None,
        "reviewer_real_name": review.reviewer_real_name,
        "reviewer_email": review.customer.email,
        "reviewer_role": review.customer.get_role_display(),
        "is_anonymous": review.is_anonymous,
        "rating": review.rating,
        "title": review.title,
        "body": review.body,
        "created_at": review.created_at.strftime("%d %b %Y %H:%M"),
        "moderation_status": review.moderation_status,
        "moderation_reason": review.moderation_reason,
        "moderated_by": str(review.moderated_by) if review.moderated_by else None,
        "moderated_at": review.moderated_at.strftime("%d %b %Y %H:%M") if review.moderated_at else None,
        "producer_name": producer_name,
        "producer_response": review.producer_response,
        "producer_responded_at": review.producer_responded_at.strftime("%d %b %Y %H:%M") if review.producer_responded_at else None,
        "response_moderation_status": review.response_moderation_status,
        "response_moderated_by": str(review.response_moderated_by) if review.response_moderated_by else None,
        "response_moderated_at": review.response_moderated_at.strftime("%d %b %Y %H:%M") if review.response_moderated_at else None,
        "history": history,
    }

    return JsonResponse(data)
