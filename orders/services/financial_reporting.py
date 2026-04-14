"""Financial reporting helpers for TC-025 admin commission reporting.

This module intentionally keeps reporting calculations and serialization
outside ``admin.py`` so admin classes remain thin and testable.
"""

from decimal import Decimal, ROUND_HALF_UP
import csv

from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone

from orders.models import Payment, ProducerOrder, get_producer_display_name

TWOPLACES = Decimal("0.01")


def quantize_money(value):
    """Return a money value rounded to two decimal places using Decimal.

    Args:
        value: Decimal-like value to quantize.

    Returns:
        Decimal: value quantized to ``0.01`` with ``ROUND_HALF_UP``.
    """
    if value is None:
        value = Decimal("0.00")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def as_money_str(value):
    """Format a money value as a 2dp string for display/export."""
    return f"{quantize_money(value):.2f}"


def _aggregate_qs(queryset, money_field):
    """Run the standard Sum/Count aggregation on an order-level queryset."""
    aggregates = queryset.aggregate(
        total_order_value=Coalesce(
            Sum("total"),
            Value(Decimal("0.00"), output_field=money_field),
        ),
        total_commission=Coalesce(
            Sum("commission_amount"),
            Value(Decimal("0.00"), output_field=money_field),
        ),
        total_producer_payout=Coalesce(
            Sum("producer_payment"),
            Value(Decimal("0.00"), output_field=money_field),
        ),
        order_count=Count("id"),
    )
    return {
        "total_order_value": quantize_money(aggregates["total_order_value"]),
        "total_commission": quantize_money(aggregates["total_commission"]),
        "total_producer_payout": quantize_money(aggregates["total_producer_payout"]),
        "order_count": int(aggregates["order_count"]),
    }


def _aggregate_producer_qs(sub_orders_qs, money_field):
    """Run the standard Sum/Count aggregation on a ProducerOrder queryset."""
    aggregates = sub_orders_qs.aggregate(
        total_order_value=Coalesce(
            Sum("subtotal"),
            Value(Decimal("0.00"), output_field=money_field),
        ),
        total_commission=Coalesce(
            Sum("commission_amount"),
            Value(Decimal("0.00"), output_field=money_field),
        ),
        total_producer_payout=Coalesce(
            Sum("producer_payment"),
            Value(Decimal("0.00"), output_field=money_field),
        ),
        order_count=Count("order", distinct=True),
    )
    return {
        "total_order_value": quantize_money(aggregates["total_order_value"]),
        "total_commission": quantize_money(aggregates["total_commission"]),
        "total_producer_payout": quantize_money(aggregates["total_producer_payout"]),
        "order_count": int(aggregates["order_count"]),
    }


def aggregate_financial_metrics(queryset, producer_id=None):
    """Aggregate top-level reporting metrics for a filtered order queryset.

    Returns a dict with:
    - ``total_*`` / ``order_count`` — overall totals (all payment statuses)
    - ``confirmed_*`` / ``confirmed_order_count`` — SUCCESS payments only
    - ``pending_*`` / ``pending_order_count`` — PENDING payments only

    The queryset should already enforce business scope (e.g., completed
    orders only) before calling this function.
    """
    money_field = DecimalField(max_digits=12, decimal_places=2)

    if producer_id:
        base_sub = ProducerOrder.objects.filter(
            order__in=queryset,
            producer_id=producer_id,
            is_deleted=False,
        )
        totals = _aggregate_producer_qs(base_sub, money_field)
        confirmed = _aggregate_producer_qs(
            base_sub.filter(order__payment__status__iexact=Payment.Status.SUCCESS), money_field,
        )
        pending = _aggregate_producer_qs(
            base_sub.filter(order__payment__status__iexact=Payment.Status.PENDING), money_field,
        )
        no_payment = _aggregate_producer_qs(
            base_sub.filter(order__payment__isnull=True), money_field,
        )
    else:
        totals = _aggregate_qs(queryset, money_field)
        confirmed = _aggregate_qs(
            queryset.filter(payment__status__iexact=Payment.Status.SUCCESS), money_field,
        )
        pending = _aggregate_qs(
            queryset.filter(payment__status__iexact=Payment.Status.PENDING), money_field,
        )
        no_payment = _aggregate_qs(
            queryset.filter(payment__isnull=True), money_field,
        )

    return {
        # Overall (all statuses) — kept for backward compatibility
        "total_order_value": totals["total_order_value"],
        "total_commission": totals["total_commission"],
        "total_producer_payout": totals["total_producer_payout"],
        "order_count": totals["order_count"],
        # Confirmed (SUCCESS) only
        "confirmed_order_value": confirmed["total_order_value"],
        "confirmed_commission": confirmed["total_commission"],
        "confirmed_producer_payout": confirmed["total_producer_payout"],
        "confirmed_order_count": confirmed["order_count"],
        # Pending only
        "pending_order_value": pending["total_order_value"],
        "pending_commission": pending["total_commission"],
        "pending_producer_payout": pending["total_producer_payout"],
        "pending_order_count": pending["order_count"],
        # No payment record
        "no_payment_order_count": no_payment["order_count"],
    }


def build_reconciliation_flags(order):
    """Return reconciliation values comparing order and sub-order totals.

    Args:
        order: ``Order`` instance.

    Returns:
        dict containing summed values and boolean match flags.
    """
    sub_orders = order.sub_orders.all()
    sub_commission_sum = quantize_money(
        sum((sub_order.commission_amount for sub_order in sub_orders), Decimal("0.00"))
    )
    sub_payout_sum = quantize_money(
        sum((sub_order.producer_payment for sub_order in sub_orders), Decimal("0.00"))
    )

    order_commission = quantize_money(order.commission_amount)
    order_payout = quantize_money(order.producer_payment)

    return {
        "order_commission": order_commission,
        "sub_commission_sum": sub_commission_sum,
        "commission_matches": order_commission == sub_commission_sum,
        "order_payout": order_payout,
        "sub_payout_sum": sub_payout_sum,
        "payout_matches": order_payout == sub_payout_sum,
    }


def generate_commission_csv(queryset, applied_filters=None, producer_id=None, anonymise=False):
    """Generate accounting-friendly CSV for the filtered commission report.

    CSV rows are normalized to one row per producer split (``ProducerOrder``)
    so exports are easy to reconcile in accounting systems.

    Args:
        queryset: Filtered queryset of parent orders.
        applied_filters: Optional dict of filter key/value pairs used in UI.

    Returns:
        HttpResponse: CSV download response.
    """
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    prefix = "anonymised_" if anonymise else ""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{prefix}network_commission_report_{timestamp}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(["Network Commission Report"])
    writer.writerow(["Generated At", timezone.localtime().isoformat()])

    if applied_filters:
        writer.writerow(["Applied Filters", "; ".join(f"{key}={value}" for key, value in applied_filters.items())])

    writer.writerow(["Rounding Policy", "Decimal 2dp (ROUND_HALF_UP)"])
    writer.writerow([])

    writer.writerow(
        [
            "Order Number",
            "Order Date",
            "Order Status",
            "Payment Status",
            "Order Total",
            "Order Commission",
            "Order Producer Payout",
            "Producer Order ID",
            "Producer Email",
            "Producer Name",
            "Producer Subtotal",
            "Producer Commission",
            "Producer Payout",
        ]
    )

    report_queryset = queryset.select_related("payment").prefetch_related(
        "sub_orders__producer__producer_profile"
    )

    for order in report_queryset:
        payment = getattr(order, "payment", None)
        payment_status = payment.get_status_display() if payment else "No payment record"

        sub_orders_queryset = order.sub_orders.all()
        if producer_id:
            sub_orders_queryset = sub_orders_queryset.filter(producer_id=producer_id)
        sub_orders = list(sub_orders_queryset)

        if producer_id and not sub_orders:
            continue

        if not sub_orders:
            writer.writerow(
                [
                    order.order_number,
                    timezone.localtime(order.created_at).date().isoformat(),
                    order.get_status_display(),
                    payment_status,
                    as_money_str(order.total),
                    as_money_str(order.commission_amount),
                    as_money_str(order.producer_payment),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
            continue

        for sub_order in sub_orders:
            producer_email = "REDACTED" if anonymise else sub_order.producer.email
            producer_name = "REDACTED PRODUCER" if anonymise else get_producer_display_name(sub_order.producer)

            writer.writerow(
                [
                    order.order_number,
                    timezone.localtime(order.created_at).date().isoformat(),
                    order.get_status_display(),
                    payment_status,
                    as_money_str(order.total),
                    as_money_str(order.commission_amount),
                    as_money_str(order.producer_payment),
                    sub_order.id,
                    producer_email,
                    producer_name,
                    as_money_str(sub_order.subtotal),
                    as_money_str(sub_order.commission_amount),
                    as_money_str(sub_order.producer_payment),
                ]
            )

    return response


def generate_commission_accounting_csv(queryset, producer_id=None, include_pending=False, anonymise=False):
    """Generate import-friendly accounting CSV.

    This export is optimized for accounting software ingestion:
    - header-first format (no metadata banner rows)
    - one row per producer split
    - values normalized to 2dp strings
    - optional inclusion of pending payments
    """
    timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    prefix = "anonymised_" if anonymise else ""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{prefix}network_commission_accounting_{timestamp}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            "Order Number",
            "Order Date",
            "Order Status",
            "Payment Status",
            "Transaction ID",
            "Currency",
            "Producer Order ID",
            "Producer Email",
            "Producer Name",
            "Producer Subtotal",
            "Producer Commission",
            "Producer Payout",
        ]
    )

    report_queryset = queryset.select_related("payment").prefetch_related(
        "sub_orders__producer__producer_profile"
    )

    for order in report_queryset:
        payment = getattr(order, "payment", None)
        payment_status = payment.get_status_display() if payment else "No payment record"

        if not include_pending:
            if not payment or payment.status.upper() != Payment.Status.SUCCESS:
                continue

        sub_orders_queryset = order.sub_orders.all()
        if producer_id:
            sub_orders_queryset = sub_orders_queryset.filter(producer_id=producer_id)
        sub_orders = list(sub_orders_queryset)

        if producer_id and not sub_orders:
            continue

        for sub_order in sub_orders:
            producer_email = "REDACTED" if anonymise else sub_order.producer.email
            producer_name = "REDACTED PRODUCER" if anonymise else get_producer_display_name(sub_order.producer)
            transaction_id = "REDACTED" if anonymise else (payment.transaction_id if payment else "")

            writer.writerow(
                [
                    order.order_number,
                    timezone.localtime(order.created_at).date().isoformat(),
                    order.get_status_display(),
                    payment_status,
                    transaction_id,
                    "GBP",
                    sub_order.id,
                    producer_email,
                    producer_name,
                    as_money_str(sub_order.subtotal),
                    as_money_str(sub_order.commission_amount),
                    as_money_str(sub_order.producer_payment),
                ]
            )

    return response
