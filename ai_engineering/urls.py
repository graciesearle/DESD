from django.urls import path

from .views import HealthcheckView

app_name = "ai_engineering"

urlpatterns = [
    path("health/", HealthcheckView.as_view(), name="health"),
]
