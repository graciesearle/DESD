from django.urls import path

from . import ui_views

app_name = "ai_web"

urlpatterns = [
    path("engineer/", ui_views.ai_engineer_dashboard, name="engineer_dashboard"),
    path("producer/", ui_views.producer_ai_workbench, name="producer_workbench"),
    path("admin/", ui_views.admin_ai_insights, name="admin_insights"),
]
