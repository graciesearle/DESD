from django.db.models import Avg
from django.shortcuts import render
from django.urls import reverse

from accounts.decorators import admin_required, ai_engineer_or_admin_required, producer_required

from ai_engineering.models import (
    AIModelVersion,
    ActiveModel,
    ExportJob,
    InferenceRequestLog,
    ProducerOverrideEvent,
)
from products.models import Product


LIFECYCLE_UI_ACTIONS = [
    {
        "key": "models",
        "title": "List Models",
        "description": "View all AI models available in the system.",
        "route": "ai_web:engineer_models",
        "api_url": "/api/ai/models/",
        "method": "GET",
        "category": "Lifecycle Management",
    },
    {
        "key": "sync",
        "title": "Sync With AAI",
        "description": "Synchronize local model registry with the AAI service.",
        "route": "ai_web:engineer_sync",
        "api_url": "/api/ai/models/sync/",
        "method": "POST",
        "category": "Lifecycle Management",
    },
    {
        "key": "upload",
        "title": "Upload Model",
        "description": "Upload a new model artifact or metadata.",
        "route": "ai_web:engineer_upload",
        "api_url": "/api/ai/models/upload/",
        "method": "POST",
        "category": "Lifecycle Management",
        "raw_example": (
            "{\n"
            '  "model_name": "produce-quality",\n'
            '  "model_version": "1.0.1",\n'
            '  "framework": "pytorch",\n'
            '  "artifact_path": "s3://models/produce-quality/1.0.1/model.pth",\n'
            '  "checksum": "sha256:...",\n'
            '  "manifest_json": {}\n'
            "}"
        ),
    },
    {
        "key": "activate",
        "title": "Activate Model",
        "description": "Mark a specific model version as 'Active'.",
        "route": "ai_web:engineer_activate",
        "api_url": "/api/ai/models/activate/",
        "method": "POST",
        "category": "Lifecycle Management",
        "raw_example": "{\n" '  "model_name": "produce-quality",\n' '  "model_version": "1.0.1"\n' "}",
    },
    {
        "key": "rollback",
        "title": "Rollback Model",
        "description": "Revert to the previous active model version.",
        "route": "ai_web:engineer_rollback",
        "api_url": "/api/ai/models/rollback/",
        "method": "POST",
        "category": "Lifecycle Management",
        "raw_example": "{\n" '  "model_name": "produce-quality"\n' "}",
    },
    {
        "key": "export",
        "title": "Create Retraining Export",
        "description": "Export quality inference logs for model retraining.",
        "route": "ai_web:engineer_export",
        "api_url": "/api/ai/exports/retraining/",
        "method": "POST",
        "category": "Lifecycle Management",
        "raw_example": (
            "{\n"
            '  "anonymise": true,\n'
            '  "started_after": "2026-04-01T00:00:00Z",\n'
            '  "started_before": "2026-04-30T23:59:59Z"\n'
            "}"
        ),
    },
    {
        "key": "recommendation_test",
        "title": "Recommendation Engine",
        "description": "Test the 'Frequently Bought Together' engine (Task 1).",
        "route": "ai_web:recommendation_test",
        "api_url": "/api/ai/recommend/",
        "method": "POST",
        "category": "Task 1: Recommendations",
        "raw_example": (
            "{\n"
            '  "recent_items": ["Apples", "Milk"],\n'
            '  "model_version": "0.1.0"\n'
            "}"
        ),
    },
    {
        "key": "order_export",
        "title": "Export Orders for Training",
        "description": "Export order history for FBT training (Task 1).",
        "route": "ai_web:engineer_order_export",
        "api_url": "/api/ai/exports/retraining/",
        "method": "POST",
        "category": "Task 1: Recommendations",
        "raw_example": (
            "{\n"
            '  "export_type": "ORDER_FBT",\n'
            '  "anonymise": true,\n'
            '  "started_after": "2026-04-01T00:00:00Z"\n'
            "}"
        ),
    },
]


def _lifecycle_action_cards(*, current_key: str | None = None):
    cards = []
    for item in LIFECYCLE_UI_ACTIONS:
        cards.append(
            {
                **item,
                "url": reverse(item["route"]),
                "is_current": item["key"] == current_key,
            }
        )
    return cards


def _get_lifecycle_action(action_key: str):
    for item in LIFECYCLE_UI_ACTIONS:
        if item["key"] == action_key:
            return item
    return None


def _render_lifecycle_page(request, *, action_key: str):
    action = _get_lifecycle_action(action_key)
    if action is None:
        raise ValueError(f"Unknown lifecycle action key: {action_key}")

    versions = list(
        AIModelVersion.objects.order_by("model_name", "-created_at")
        .values("model_name", "model_version")[:200]
    )
    model_names = sorted({item["model_name"] for item in versions if item.get("model_name")})

    context = {
        "action": {
            **action,
            "url": reverse(action["route"]),
        },
        "lifecycle_actions": _lifecycle_action_cards(current_key=action_key),
        "model_versions": versions,
        "model_names": model_names,
    }
    return render(request, "ai_engineering/ai_engineer_lifecycle_action.html", context)


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_dashboard(request):
    active_model = ActiveModel.objects.filter(is_active=True).select_related("model_version").first()
    recent_models = AIModelVersion.objects.all().order_by("-created_at")[:12]
    recent_exports = ExportJob.objects.select_related("requested_by").order_by("-started_at")[:10]
    recent_predictions = (
        InferenceRequestLog.objects.select_related("producer")
        .order_by("-created_at")[:15]
    )

    context = {
        "active_model": active_model,
        "recent_models": recent_models,
        "recent_exports": recent_exports,
        "recent_predictions": recent_predictions,
        "model_count": AIModelVersion.objects.count(),
        "export_count": ExportJob.objects.count(),
        "prediction_count": InferenceRequestLog.objects.count(),
        "lifecycle_actions": _lifecycle_action_cards(),
        "api_links": {
            "models_list": "/api/ai/models/",
            "model_upload": "/api/ai/models/upload/",
            "model_activate": "/api/ai/models/activate/",
            "model_rollback": "/api/ai/models/rollback/",
            "export_create": "/api/ai/exports/retraining/",
        },
    }
    return render(request, "ai_engineering/ai_engineer_dashboard.html", context)


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_models_page(request):
    return _render_lifecycle_page(request, action_key="models")


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_sync_page(request):
    return _render_lifecycle_page(request, action_key="sync")


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_upload_page(request):
    return _render_lifecycle_page(request, action_key="upload")


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_activate_page(request):
    return _render_lifecycle_page(request, action_key="activate")


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_rollback_page(request):
    return _render_lifecycle_page(request, action_key="rollback")


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_export_page(request):
    return _render_lifecycle_page(request, action_key="export")


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_order_export_page(request):
    return _render_lifecycle_page(request, action_key="order_export")


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def recommendation_test_page(request):
    action = _get_lifecycle_action("recommendation_test")
    context = {
        "action": action,
        "lifecycle_actions": _lifecycle_action_cards(current_key="recommendation_test"),
    }
    return render(request, "ai_engineering/recommendation_test.html", context)


@producer_required(redirect_url="marketplace:product_list")
def producer_ai_workbench(request):
    producer_products = Product.objects.filter(producer=request.user).order_by("name").only("id", "name")[:200]
    recent_predictions = (
        InferenceRequestLog.objects.filter(producer=request.user)
        .order_by("-created_at")
        .only(
            "id",
            "created_at",
            "authoritative_grade",
            "confidence",
            "predicted_class",
            "recommendation_action",
            "model_version_used",
        )[:15]
    )
    recent_overrides = (
        ProducerOverrideEvent.objects.filter(producer=request.user)
        .select_related("inference_log")
        .order_by("-created_at")[:10]
    )

    context = {
        "recent_predictions": recent_predictions,
        "recent_overrides": recent_overrides,
        "producer_products": producer_products,
        "api_links": {
            "predict": "/api/ai/producer-quality/predict/",
            "override": "/api/ai/producer-quality/override/",
        },
    }
    return render(request, "ai_engineering/producer_ai_workbench.html", context)


@admin_required(redirect_url="marketplace:product_list")
def admin_ai_insights(request):
    total_predictions = InferenceRequestLog.objects.count()
    total_overrides = ProducerOverrideEvent.objects.count()
    avg_confidence = InferenceRequestLog.objects.aggregate(avg=Avg("confidence"))["avg"] or 0
    active_model = ActiveModel.objects.filter(is_active=True).select_related("model_version").first()

    confidence_distribution = {
        "high": InferenceRequestLog.objects.filter(confidence__gte=80).count(),
        "medium": InferenceRequestLog.objects.filter(confidence__gte=60, confidence__lt=80).count(),
        "low": InferenceRequestLog.objects.filter(confidence__lt=60).count(),
    }

    recent_predictions = InferenceRequestLog.objects.select_related("producer").order_by("-created_at")[:15]

    context = {
        "total_predictions": total_predictions,
        "total_overrides": total_overrides,
        "avg_confidence": float(avg_confidence),
        "active_model": active_model,
        "confidence_distribution": confidence_distribution,
        "recent_predictions": recent_predictions,
        "api_links": {
            "metrics": "/api/ai/admin/metrics/",
            "explanation_prefix": "/api/ai/admin/predictions/",
        },
    }
    return render(request, "ai_engineering/admin_ai_insights.html", context)
