from django.contrib import admin
from django.utils.safestring import mark_safe

from ai_engineering.models import (
    AIModelVersion,
    ActiveModel,
    ExportJob,
    InferenceRequestLog,
    ProducerOverrideEvent,
    AdminExplanationReview,
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

@admin.register(AdminExplanationReview)
class AdminExplanationReviewAdmin(admin.ModelAdmin):
    list_display = ("inference_log", "admin", "model_prediction", "agreed_with_model", "created_at")
    list_filter = ("agreed_with_model", "created_at")
    
    # These fields are snapshots for traceability, so we make them read-only
    readonly_fields = ("model_prediction", "generated_explanation", "display_xai_report", "created_at")
    
    # This organizes the view when you click into a specific review
    fieldsets = (
        ("Audit Metadata", {
            "fields": ("inference_log", "admin", "created_at")
        }),
        ("Traceability Evidence", {
            "fields": ("display_xai_report", "model_prediction"),
            "description": "This is the actual image the administrator saw when they performed this audit."
        }),
        ("Admin Decision", {
            "fields": ("agreed_with_model", "review_notes")
        }),
        ("Raw Snapshot Data", {
            "classes": ("collapse",), # Hides the messy JSON by default
            "fields": ("generated_explanation",),
        }),
    )

    # This method extracts the Base64 and turns it into an <img> tag
    def display_xai_report(self, obj):
        base64_str = obj.generated_explanation.get("xai_report_base64")
        if not base64_str:
            return "No visual XAI report was generated for this audit."
        
        # We wrap the base64 string in a standard HTML img tag
        return mark_safe(
            f'<img src="data:image/jpeg;base64,{base64_str}" '
            f'style="max-width: 600px; height: auto; border: 1px solid #ccc; border-radius: 8px;" />'
        )
    
    display_xai_report.short_description = "Visual XAI Report Snapshot"