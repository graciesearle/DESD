from django.urls import path

from .views import (
    AdminMetricsView,
    BatchGradeEditView,
    ExportJobDetailView,
    HealthcheckView,
    IntakeCommitView,
    ModelActivateView,
    ModelListView,
    ModelRollbackView,
    ModelSyncView,
    ModelUploadView,
    PredictionExplanationView,
    ProducerModelChoicesView,
    ProducerQualityOverrideView,
    ProducerQualityPredictView,
    RetrainingExportCreateView,
    BatchCreateView,
    RecommendationPredictView,
)

app_name = "ai_engineering"

urlpatterns = [
    path("health/", HealthcheckView.as_view(), name="health"),
    path("models/", ModelListView.as_view(), name="model-list"),
    path("models/sync/", ModelSyncView.as_view(), name="model-sync"),
    path("models/upload/", ModelUploadView.as_view(), name="model-upload"),
    path("models/activate/", ModelActivateView.as_view(), name="model-activate"),
    path("models/rollback/", ModelRollbackView.as_view(), name="model-rollback"),
    path("producer-quality/models/", ProducerModelChoicesView.as_view(), name="producer-model-choices"),
    path("producer-quality/predict/", ProducerQualityPredictView.as_view(), name="producer-predict"),
    path("producer-quality/override/", ProducerQualityOverrideView.as_view(), name="producer-override"),
    path("producer-quality/intake/commit/", IntakeCommitView.as_view(), name="intake-commit"),
    path("producer-quality/batches/create/", BatchCreateView.as_view(), name="batch-create"),
    path("producer-quality/batches/<int:batch_id>/grade/", BatchGradeEditView.as_view(), name="batch-grade-edit"),
    path("recommend/", RecommendationPredictView.as_view(), name="recommendation-predict"),
    path("exports/retraining/", RetrainingExportCreateView.as_view(), name="retraining-export"),
    path("exports/<int:pk>/", ExportJobDetailView.as_view(), name="export-detail"),
    path("admin/metrics/", AdminMetricsView.as_view(), name="admin-metrics"),
    path(
        "admin/predictions/<int:pk>/explanation/",
        PredictionExplanationView.as_view(),
        name="prediction-explanation",
    ),
]
