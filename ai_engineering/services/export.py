import csv
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from ai_engineering.models import ExportJob, InferenceRequestLog


def create_retraining_export(job: ExportJob) -> ExportJob:
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
