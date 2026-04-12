from django.db.models import Avg
from django.shortcuts import render

from accounts.decorators import admin_required, ai_engineer_or_admin_required, producer_required

from ai_engineering.models import (
    AIModelVersion,
    ActiveModel,
    ExportJob,
    InferenceRequestLog,
    ProducerOverrideEvent,
)
from products.models import Product


@ai_engineer_or_admin_required(redirect_url="marketplace:product_list")
def ai_engineer_dashboard(request):
    active_model = ActiveModel.objects.filter(is_active=True).select_related("model_version").first()
    recent_models = AIModelVersion.objects.all().order_by("-created_at")[:12]
    recent_exports = ExportJob.objects.select_related("requested_by").order_by("-started_at")[:10]

    context = {
        "active_model": active_model,
        "recent_models": recent_models,
        "recent_exports": recent_exports,
        "model_count": AIModelVersion.objects.count(),
        "export_count": ExportJob.objects.count(),
        "api_links": {
            "models_list": "/api/ai/models/",
            "model_upload": "/api/ai/models/upload/",
            "model_activate": "/api/ai/models/activate/",
            "model_rollback": "/api/ai/models/rollback/",
            "export_create": "/api/ai/exports/retraining/",
        },
    }
    return render(request, "ai_engineering/ai_engineer_dashboard.html", context)


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
