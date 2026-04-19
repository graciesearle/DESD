from django.urls import path

from . import ui_views

app_name = "ai_web"

urlpatterns = [
    path("engineer/", ui_views.ai_engineer_dashboard, name="engineer_dashboard"),
    path("engineer/lifecycle/models/", ui_views.ai_engineer_models_page, name="engineer_models"),
    path("engineer/lifecycle/sync/", ui_views.ai_engineer_sync_page, name="engineer_sync"),
    path("engineer/lifecycle/upload/", ui_views.ai_engineer_upload_page, name="engineer_upload"),
    path("engineer/lifecycle/activate/", ui_views.ai_engineer_activate_page, name="engineer_activate"),
    path("engineer/lifecycle/rollback/", ui_views.ai_engineer_rollback_page, name="engineer_rollback"),
    path("engineer/lifecycle/export/", ui_views.ai_engineer_export_page, name="engineer_export"),
    path("producer/", ui_views.producer_ai_workbench, name="producer_workbench"),
    path("admin/", ui_views.admin_ai_insights, name="admin_insights"),
]
