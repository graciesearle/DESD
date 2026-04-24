import csv
import zipfile
import io
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from ai_engineering.models import ExportJob, InferenceRequestLog
from orders.models import OrderItem


def _cleanup_old_exports(keep_count=10):
    """
    Keep only the most recent export files to prevent container storage buildup.
    """
    export_dir = Path(settings.AI_EXPORT_DIR)
    if not export_dir.exists():
        return

    # Sort files by modification time (newest first)
    files = sorted(export_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    # Delete everything beyond the keep_count
    for old_file in files[keep_count:]:
        try:
            old_file.unlink()
        except Exception:
            pass


def create_retraining_export(job: ExportJob) -> ExportJob:
    _cleanup_old_exports()
    queryset = InferenceRequestLog.objects.select_related("producer", "product").prefetch_related("overrides")

    started_after = job.filter_json.get("started_after")
    if started_after:
        queryset = queryset.filter(created_at__gte=started_after)

    started_before = job.filter_json.get("started_before")
    if started_before:
        queryset = queryset.filter(created_at__lte=started_before)

    export_dir = Path(settings.AI_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)

    filename = f"retraining_export_{timezone.localtime().strftime('%Y%m%d_%H%M%S')}.csv"
    output_path = export_dir / filename

    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            [
                "inference_id",
                "producer_id",
                "product_id",
                "color_score",
                "size_score",
                "ripeness_score",
                "confidence",
                "predicted_class",
                "ai_reported_grade",
                "authoritative_grade",
                "recommendation_action",
                "accepted_recommendation",
                "override_grade",
                "override_reason",
                "model_version_used",
                "created_at",
            ]
        )

        row_count = 0
        for inference in queryset.order_by("id"):
            latest_override = inference.overrides.order_by("-created_at").first()
            producer_id = inference.producer_id
            if job.anonymised:
                producer_id = f"anon_{inference.producer_id}"

            writer.writerow(
                [
                    inference.id,
                    producer_id,
                    inference.product_id or "",
                    inference.color_score,
                    inference.size_score,
                    inference.ripeness_score,
                    inference.confidence,
                    inference.predicted_class,
                    inference.ai_reported_grade or "",
                    inference.authoritative_grade,
                    inference.recommendation_action,
                    latest_override.accepted_recommendation if latest_override else "",
                    latest_override.override_grade if latest_override else "",
                    latest_override.override_reason if latest_override else "",
                    inference.model_version_used,
                    inference.created_at.isoformat(),
                ]
            )
            row_count += 1

    job.output_path = str(output_path)
    job.row_count = row_count
    job.status = ExportJob.Status.COMPLETED
    job.completed_at = timezone.now()
    job.error_message = ""
    job.save(update_fields=["output_path", "row_count", "status", "completed_at", "error_message"])
    return job


def create_order_fbt_export(job: ExportJob) -> ExportJob:
    _cleanup_old_exports()
    """
    Export order history in a format suitable for Task 1 (Recommendation Engine).
    Format: Member_number, Date, itemDescription
    """
    queryset = OrderItem.objects.select_related("order").filter(order__status="DELIVERED")

    started_after = job.filter_json.get("started_after")
    if started_after:
        queryset = queryset.filter(order__created_at__gte=started_after)

    started_before = job.filter_json.get("started_before")
    if started_before:
        queryset = queryset.filter(order__created_at__lte=started_before)

    export_dir = Path(settings.AI_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)

    filename = f"order_fbt_export_{timezone.localtime().strftime('%Y%m%d_%H%M%S')}.csv"
    output_path = export_dir / filename

    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Member_number", "Date", "itemDescription"])

        row_count = 0
        for item in queryset.order_by("order__id"):
            # Use customer ID or anonymised ID
            customer_id = item.order.customer_id
            if job.anonymised:
                customer_id = f"anon_{customer_id}"

            # Format date as DD-MM-YYYY to match Groceries_dataset format
            date_str = item.order.created_at.strftime("%d-%m-%Y")

            # Strip quality grades (e.g. "Carrots (Grade B)" -> "Carrots")
            item_name = item.product_name
            if " (Grade " in item_name:
                item_name = item_name.split(" (Grade ")[0]

            writer.writerow([customer_id, date_str, item_name])
            row_count += 1

    job.output_path = str(output_path)
    job.row_count = row_count
    job.status = ExportJob.Status.COMPLETED
    job.completed_at = timezone.now()
    job.error_message = ""
def create_next_basket_export(job: ExportJob) -> ExportJob:
    """
    Export rich feature set for Task 1 (Next Basket Prediction).
    Generates user_features, user_product_features, and prod_features.
    """
    _cleanup_old_exports()
    from collections import defaultdict
    from datetime import datetime

    # 1. Fetch Order History
    # We only care about delivered orders for feature engineering
    items = OrderItem.objects.select_related("order", "product").filter(order__status="DELIVERED").order_by("order__created_at")

    # Data structures for feature calculation
    user_orders = defaultdict(list) # user_id -> [list of order dates]
    user_prod_counts = defaultdict(int) # (user_id, prod_id) -> count
    user_prod_last_order = defaultdict(int) # (user_id, prod_id) -> last_order_num_for_this_user
    prod_counts = defaultdict(int) # prod_id -> total site-wide purchases
    prod_reorders = defaultdict(int) # prod_id -> total site-wide reorders
    
    # Track which users have bought which products before
    user_ever_bought = defaultdict(set) # user_id -> {set of product_ids}
    
    user_order_counter = defaultdict(int) # user_id -> current_order_sequence_num
    
    all_users = set()
    all_prods = {} # prod_id -> prod_name

    for item in items:
        u_id = item.order.customer_id
        p_id = item.product_id or 0
        all_users.add(u_id)
        if p_id:
            # Strip grades from name for a cleaner export/AI mapping
            p_name = item.product.name
            if " (Grade " in p_name:
                p_name = p_name.split(" (Grade ")[0]
            
            all_prods[p_id] = p_name
        
        # Site-wide prod stats
        prod_counts[p_id] += 1
        if p_id in user_ever_bought[u_id]:
            prod_reorders[p_id] += 1
        user_ever_bought[u_id].add(p_id)

        # User sequence tracking
        # We need to know which order number this was for THIS user
        order_key = (u_id, item.order.id)
        if not hasattr(item.order, '_seq_num'):
            user_order_counter[u_id] += 1
            item.order._seq_num = user_order_counter[u_id]
            user_orders[u_id].append(item.order.created_at)

        # User-Product stats
        user_prod_counts[(u_id, p_id)] += 1
        user_prod_last_order[(u_id, p_id)] = item.order._seq_num

    # 2. Build User Features CSV
    user_features_data = []
    for u_id in all_users:
        dates = sorted(user_orders[u_id])
        total_orders = len(dates)
        avg_days = 0
        if total_orders > 1:
            diffs = [(dates[i] - dates[i-1]).days for i in range(1, total_orders)]
            avg_days = sum(diffs) / len(diffs)
        
        user_features_data.append([u_id, total_orders, round(avg_days, 2)])

    # 3. Build User-Product Features CSV
    up_features_data = []
    for (u_id, p_id), count in user_prod_counts.items():
        up_features_data.append([u_id, p_id, count, user_prod_last_order[(u_id, p_id)], all_prods.get(p_id, "Unknown")])

    # 4. Build Product Features CSV
    prod_features_data = []
    for p_id, count in prod_counts.items():
        reorder_rate = prod_reorders[p_id] / count if count > 0 else 0
        prod_features_data.append([p_id, count, round(reorder_rate, 4), all_prods.get(p_id, "Unknown")])

    # 5. Pack into files
    export_dir = Path(settings.AI_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)
    
    # We create a ZIP to keep all 3 files together
    zip_filename = f"next_basket_features_{timezone.localtime().strftime('%Y%m%d_%H%M%S')}.zip"
    output_path = export_dir / zip_filename
    
    with zipfile.ZipFile(output_path, 'w') as zipf:
        # User Features
        u_buf = io.StringIO()
        u_writer = csv.writer(u_buf)
        u_writer.writerow(["user_id", "user_total_orders", "user_avg_days_between"])
        u_writer.writerows(user_features_data)
        zipf.writestr("user_features.csv", u_buf.getvalue())
        
        # User-Product Features
        up_buf = io.StringIO()
        up_writer = csv.writer(up_buf)
        up_writer.writerow(["user_id", "product_id", "up_total_bought", "up_last_order_num", "product_name"])
        up_writer.writerows(up_features_data)
        zipf.writestr("user_product_features.csv", up_buf.getvalue())
        
        # Product Features
        p_buf = io.StringIO()
        p_writer = csv.writer(p_buf)
        p_writer.writerow(["product_id", "prod_total_purchases", "prod_reorder_rate", "product_name"])
        p_writer.writerows(prod_features_data)
        zipf.writestr("prod_features.csv", p_buf.getvalue())

    job.output_path = str(output_path)
    job.row_count = len(up_features_data)
    job.status = ExportJob.Status.COMPLETED
    job.completed_at = timezone.now()
    job.save()
    return job
