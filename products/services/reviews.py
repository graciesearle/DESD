from dataclasses import dataclass

from orders.models import Order

from products.models import Review


@dataclass(frozen=True)
class ReviewEligibility:
    can_review: bool
    code: str
    message: str
    existing_review: Review | None = None


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

    review = existing_review
    if review is None:
        review = Review.objects.filter(
            customer=user,
            product_id=order_item.product_id,
            is_deleted=False,
        ).first()

    if review is not None:
        return ReviewEligibility(
            False,
            "duplicate_review",
            "You already reviewed this product.",
            existing_review=review,
        )

    return ReviewEligibility(True, "ok", "Review can be submitted.")
