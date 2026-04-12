from django.urls import path

from .views import (
    AdminMetricsView,
    ExportJobDetailView,
    HealthcheckView,
    ModelActivateView,
    ModelListView,
    ModelRollbackView,
    ModelUploadView,
    PredictionExplanationView,
    ProducerQualityOverrideView,
    ProducerQualityPredictView,
    RetrainingExportCreateView,
)

app_name = "ai_engineering"

urlpatterns = [
    path("health/", HealthcheckView.as_view(), name="health"),
    path("models/", ModelListView.as_view(), name="model-list"),
    path("models/upload/", ModelUploadView.as_view(), name="model-upload"),
    path("models/activate/", ModelActivateView.as_view(), name="model-activate"),
    path("models/rollback/", ModelRollbackView.as_view(), name="model-rollback"),
    path("producer-quality/predict/", ProducerQualityPredictView.as_view(), name="producer-predict"),
    path("producer-quality/override/", ProducerQualityOverrideView.as_view(), name="producer-override"),
    path("exports/retraining/", RetrainingExportCreateView.as_view(), name="retraining-export"),
    path("exports/<int:pk>/", ExportJobDetailView.as_view(), name="export-detail"),
    path("admin/metrics/", AdminMetricsView.as_view(), name="admin-metrics"),
    path(
        "admin/predictions/<int:pk>/explanation/",
        PredictionExplanationView.as_view(),
        name="prediction-explanation",
    ),
]
