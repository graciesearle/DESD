from dataclasses import dataclass

from django.utils import timezone
from datetime import timedelta
from orders.models import Order, OrderItem
from products.models import Product, Review


@dataclass(frozen=True)
class ReviewEligibility:
    can_review: bool
    code: str
    message: str
    existing_review: Review | None = None


@dataclass(frozen=True)
class ProductReviewEligibility:
    previously_purchased: bool
    can_review: bool
    code: str
    message: str
    existing_review: Review | None = None
    order: Order | None = None
    order_item_id: int | None = None


def review_eligibility_for_order_item(*, user, order, order_item, existing_review=None):
    """Return review eligibility for a specific purchased order item."""
    if not getattr(user, "is_authenticated", False):
        return ReviewEligibility(False, "not_authenticated", "Please sign in to leave a review.")

    if not getattr(user, "is_customer", False):
        return ReviewEligibility(False, "role_not_allowed", "Only customers can leave reviews.")

    if order.customer_id != user.id:
        return ReviewEligibility(False, "order_not_owned", "You can only review your own orders.")

    if order_item.order_id != order.id:
        return ReviewEligibility(False, "item_not_in_order", "This item is not part of the selected order.")

    if order.status != Order.Status.DELIVERED:
        return ReviewEligibility(
            False,
            "order_not_delivered",
            "You can review this product once the order is marked as delivered.",
        )

    if not order_item.product_id:
        return ReviewEligibility(
            False,
            "product_unavailable",
            "This product is no longer available for review.",
        )

    # TC-031: 30-day review window
    thirty_days_ago = timezone.now() - timedelta(days=30)
    if order.created_at < thirty_days_ago:
        return ReviewEligibility(
            False,
            "order_too_old",
            "Reviews can only be submitted for orders placed within the last 30 days.",
        )

    review = existing_review
    if review is None:
        review = Review.objects.filter(
            customer=user,
            product_id=order_item.product_id,
            is_deleted=False,
        ).exclude(moderation_status='REJECTED').first()

    if review is not None:
        return ReviewEligibility(
            False,
            "duplicate_review",
            "You already reviewed this product.",
            existing_review=review,
        )

    return ReviewEligibility(True, "ok", "Review can be submitted.")


def review_eligibility_for_product(*, user, product: Product):
    """Return product-page review eligibility for a logged-in customer."""
    if not getattr(user, "is_authenticated", False):
        return ProductReviewEligibility(
            previously_purchased=False,
            can_review=False,
            code="not_authenticated",
            message="Please sign in to leave a review.",
        )

    if not getattr(user, "is_customer", False):
        return ProductReviewEligibility(
            previously_purchased=False,
            can_review=False,
            code="role_not_allowed",
            message="Only customers can leave reviews.",
        )

    existing_review = Review.objects.filter(
        customer=user,
        product=product,
        is_deleted=False,
    ).exclude(moderation_status='REJECTED').first()

    thirty_days_ago = timezone.now() - timedelta(days=30)
    purchased_items = (
        OrderItem.objects.select_related("order")
        .filter(
            order__customer=user,
            order__is_deleted=False,
            order__created_at__gte=thirty_days_ago,
            product=product,
        )
        .exclude(order__status=Order.Status.CANCELLED)
        .order_by("-order__created_at", "-id")
    )

    previously_purchased = purchased_items.exists() or existing_review is not None

    if existing_review is not None:
        return ProductReviewEligibility(
            previously_purchased=previously_purchased,
            can_review=False,
            code="duplicate_review",
            message="You already reviewed this product.",
            existing_review=existing_review,
        )

    delivered_item = purchased_items.filter(order__status=Order.Status.DELIVERED).first()
    if delivered_item is not None:
        return ProductReviewEligibility(
            previously_purchased=previously_purchased,
            can_review=True,
            code="ok",
            message="Review can be submitted.",
            order=delivered_item.order,
            order_item_id=delivered_item.id,
        )

    if previously_purchased:
        return ProductReviewEligibility(
            previously_purchased=True,
            can_review=False,
            code="order_not_delivered",
            message="You can review this product once the order is marked as delivered.",
        )

    return ProductReviewEligibility(
        previously_purchased=False,
        can_review=False,
        code="not_purchased",
        message="Purchase this product to leave a review.",
    )
