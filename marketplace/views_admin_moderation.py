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
    Consolidated moderation queue for reviews, producer responses, and community comments.
    """
    from django.shortcuts import render
    from marketplace.models import Comment
    import datetime

    reviews_qs = (
        Review.all_objects
        .filter(is_deleted=False)
        .select_related(
            "product", "product__producer", "product__producer__producer_profile",
            "customer", "customer__customer_profile",
            "moderated_by", "response_moderated_by",
        )
    )

    comments_qs = (
        Comment.all_objects
        .filter(is_deleted=False)
        .select_related(
            "author", "post", "recipe", "moderated_by", "parent"
        )
    )

    # ── Filters ──────────────────────────────────────────────────
    status_filter = request.GET.get("status", "action_required")
    role_filter = request.GET.get("role", "")
    producer_filter = request.GET.get("producer", "")
    type_filter = request.GET.get("item_type", "")
    search_query = request.GET.get("q", "").strip()
    sort_by = request.GET.get("sort", "newest")

    if status_filter == "action_required":
        reviews_qs = reviews_qs.filter(
            Q(moderation_status=ModerationStatus.PENDING)
            | Q(response_moderation_status=ModerationStatus.PENDING, producer_response__gt="")
        )
        comments_qs = comments_qs.filter(moderation_status=ModerationStatus.PENDING)
    elif status_filter in ModerationStatus.values:
        reviews_qs = reviews_qs.filter(moderation_status=status_filter)
        comments_qs = comments_qs.filter(moderation_status=status_filter)

    if role_filter:
        reviews_qs = reviews_qs.filter(customer__role=role_filter)
        comments_qs = comments_qs.filter(author__role=role_filter)

    if producer_filter and producer_filter.isdigit():
        reviews_qs = reviews_qs.filter(product__producer_id=producer_filter)
        comments_qs = comments_qs.filter(
            Q(post__producer_id=producer_filter) | Q(recipe__producer_id=producer_filter)
        )

    if type_filter == "review":
        comments_qs = comments_qs.none()
    elif type_filter == "comment":
        reviews_qs = reviews_qs.none()

    if search_query:
        reviews_qs = reviews_qs.filter(
            Q(title__icontains=search_query)
            | Q(body__icontains=search_query)
            | Q(producer_response__icontains=search_query)
            | Q(customer__email__icontains=search_query)
            | Q(product__name__icontains=search_query)
        )
        comments_qs = comments_qs.filter(
            Q(body__icontains=search_query)
            | Q(author__email__icontains=search_query)
            | Q(post__title__icontains=search_query)
            | Q(recipe__title__icontains=search_query)
        )

    reviews = list(reviews_qs)
    for r in reviews:
        r.item_type = 'review'
        r.sort_date = r.created_at

    comments = list(comments_qs)
    for c in comments:
        c.item_type = 'comment'
        c.sort_date = c.created_at

    items = reviews + comments

    # ── Sorting ──────────────────────────────────────────────────
    def get_rating(item):
        return item.rating if item.item_type == 'review' else 0

    def get_moderated_at(item):
        m = item.moderated_at
        if item.item_type == 'review' and getattr(item, 'response_moderated_at', None):
            if m and item.response_moderated_at:
                m = max(m, item.response_moderated_at)
            else:
                m = m or item.response_moderated_at
        return m or timezone.make_aware(datetime.datetime.min)

    if sort_by == "oldest":
        items.sort(key=lambda x: x.sort_date)
    elif sort_by == "rating_high":
        items.sort(key=lambda x: (get_rating(x), x.sort_date.timestamp()), reverse=True)
    elif sort_by == "rating_low":
        items.sort(key=lambda x: (get_rating(x), -x.sort_date.timestamp()))
    elif sort_by == "last_moderated":
        items.sort(key=get_moderated_at, reverse=True)
    else:  # newest (default)
        items.sort(key=lambda x: x.sort_date, reverse=True)

    # ── Pagination ───────────────────────────────────────────────
    paginator = Paginator(items, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    base_query = params.urlencode()

    # ── Summary counts ───────────────────────────────────────────
    all_reviews = Review.all_objects.filter(is_deleted=False)
    all_comments = Comment.all_objects.filter(is_deleted=False)
    
    pending_reviews = all_reviews.filter(moderation_status=ModerationStatus.PENDING).count()
    pending_responses = all_reviews.filter(response_moderation_status=ModerationStatus.PENDING, producer_response__gt="").count()
    pending_comments = all_comments.filter(moderation_status=ModerationStatus.PENDING).count()

    # ── Producers for filter dropdown ────────────────────────────
    from accounts.models import CustomUser
    producer_ids = list(all_reviews.values_list("product__producer_id", flat=True))
    producer_ids += list(all_comments.filter(post__isnull=False).values_list("post__producer_id", flat=True))
    producer_ids += list(all_comments.filter(recipe__isnull=False).values_list("recipe__producer_id", flat=True))
    
    producers = (
        CustomUser.objects
        .filter(id__in=set(producer_ids), role="PRODUCER")
        .select_related("producer_profile")
        .order_by("email")
    )

    context = {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "base_query": base_query,
        "status_filter": status_filter,
        "role_filter": role_filter,
        "producer_filter": producer_filter,
        "type_filter": type_filter,
        "search_query": search_query,
        "sort_by": sort_by,
        "pending_reviews": pending_reviews,
        "pending_responses": pending_responses,
        "pending_comments": pending_comments,
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



@admin_required
@require_POST
def admin_moderate_comment(request, comment_id):
    from marketplace.models import Comment
    comment = get_object_or_404(Comment.all_objects, pk=comment_id, is_deleted=False)
    action = request.POST.get("action")
    reason = request.POST.get("reason", "").strip()

    if action == "approve":
        comment.moderation_status = ModerationStatus.APPROVED
        comment.moderation_reason = ""
    elif action == "reject":
        comment.moderation_status = ModerationStatus.REJECTED
        comment.moderation_reason = reason
    else:
        messages.error(request, "Invalid moderation action.")
        return redirect("marketplace:admin_review_moderation")

    comment.moderated_by = request.user
    comment.moderated_at = timezone.now()
    comment.save(update_fields=["moderation_status", "moderation_reason", "moderated_by", "moderated_at", "updated_at"])

    label = "approved" if action == "approve" else "rejected"
    messages.success(request, f"Comment by {comment.author.email} has been {label}.")
    return redirect("marketplace:admin_review_moderation")


# ── Bulk actions ─────────────────────────────────────────────────────

@admin_required
@require_POST
def admin_bulk_moderate(request):
    from marketplace.models import Comment
    action = request.POST.get("bulk_action")  # bulk_approve | bulk_reject
    item_ids = request.POST.getlist("item_ids")

    if not item_ids:
        messages.warning(request, "No items selected.")
        return redirect("marketplace:admin_review_moderation")

    review_ids = [int(i.split('_')[1]) for i in item_ids if i.startswith('review_')]
    comment_ids = [int(i.split('_')[1]) for i in item_ids if i.startswith('comment_')]

    review_qs = Review.all_objects.filter(pk__in=review_ids, is_deleted=False)
    comment_qs = Comment.all_objects.filter(pk__in=comment_ids, is_deleted=False)

    if action == "bulk_approve":
        review_qs.update(
            moderation_status=ModerationStatus.APPROVED,
            moderation_reason="",
            moderated_by=request.user,
            moderated_at=timezone.now(),
        )
        comment_qs.update(
            moderation_status=ModerationStatus.APPROVED,
            moderation_reason="",
            moderated_by=request.user,
            moderated_at=timezone.now(),
        )
        messages.success(request, f"{len(review_ids) + len(comment_ids)} item(s) approved.")
    elif action == "bulk_reject":
        review_qs.update(
            moderation_status=ModerationStatus.REJECTED,
            moderated_by=request.user,
            moderated_at=timezone.now(),
        )
        comment_qs.update(
            moderation_status=ModerationStatus.REJECTED,
            moderated_by=request.user,
            moderated_at=timezone.now(),
        )
        messages.success(request, f"{len(review_ids) + len(comment_ids)} item(s) rejected.")
    else:
        messages.error(request, "Invalid bulk action.")

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
    from marketplace.models import Comment
    item_type = request.GET.get('type', 'review')
    
    if item_type == 'comment':
        comment = get_object_or_404(
            Comment.all_objects.select_related("author", "post", "recipe", "moderated_by", "parent"),
            pk=review_id, is_deleted=False
        )
        history = []
        for record in comment.history.all().order_by("-history_date")[:20]:
            history.append({
                "date": record.history_date.strftime("%d %b %Y %H:%M"),
                "user": str(record.history_user or "System"),
                "reason": record.history_change_reason or "—",
                "type": record.history_type,
            })
        
        # Format target name
        target_name = "Unknown"
        target_image = None
        if comment.post:
            target_name = f"Post: {comment.post.title}"
            if comment.post.image: target_image = comment.post.image.url
        elif comment.recipe:
            target_name = f"Recipe: {comment.recipe.title}"
            if comment.recipe.image: target_image = comment.recipe.image.url
            
        data = {
            "id": comment.id,
            "item_type": "comment",
            "product_name": target_name,
            "product_id": None,
            "product_image": target_image,
            "reviewer_real_name": comment.author.email,
            "reviewer_email": comment.author.email,
            "reviewer_role": comment.author.get_role_display(),
            "is_anonymous": False,
            "rating": None,
            "title": "Community Comment",
            "body": comment.body,
            "created_at": comment.created_at.strftime("%d %b %Y %H:%M"),
            "moderation_status": comment.moderation_status,
            "moderation_reason": comment.moderation_reason,
            "moderated_by": str(comment.moderated_by) if comment.moderated_by else None,
            "moderated_at": comment.moderated_at.strftime("%d %b %Y %H:%M") if comment.moderated_at else None,
            "producer_name": None,
            "producer_response": None,
            "producer_responded_at": None,
            "response_moderation_status": None,
            "response_moderated_by": None,
            "response_moderated_at": None,
            "history": history,
        }
        return JsonResponse(data)
    else:
        # Existing review logic
        review = get_object_or_404(
            Review.all_objects.select_related(
                "product", "product__producer__producer_profile",
                "customer", "customer__customer_profile",
                "moderated_by", "response_moderated_by",
            ),
            pk=review_id,
            is_deleted=False,
        )

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
            "item_type": "review",
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
