from django.contrib import admin

from ai_engineering.models import (
    AIModelVersion,
    ActiveModel,
    ExportJob,
    InferenceRequestLog,
    ProducerOverrideEvent,
)


@admin.register(AIModelVersion)
class AIModelVersionAdmin(admin.ModelAdmin):
    list_display = ("model_name", "model_version", "framework", "created_at")
    search_fields = ("model_name", "model_version", "checksum")


@admin.register(ActiveModel)
class ActiveModelAdmin(admin.ModelAdmin):
    list_display = ("model_version", "is_active", "activated_by", "activated_at")
    list_filter = ("is_active", "activated_at")


@admin.register(InferenceRequestLog)
class InferenceRequestLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "producer",
        "predicted_class",
        "authoritative_grade",
        "recommendation_action",
        "model_version_used",
        "created_at",
    )
    list_filter = ("authoritative_grade", "model_version_used")
    search_fields = ("producer__email", "predicted_class", "model_version_used")


@admin.register(ProducerOverrideEvent)
class ProducerOverrideEventAdmin(admin.ModelAdmin):
    list_display = ("inference_log", "producer", "accepted_recommendation", "override_grade", "created_at")
    list_filter = ("accepted_recommendation", "override_grade")


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "requested_by", "status", "anonymised", "row_count", "completed_at")
    list_filter = ("status", "anonymised")
