from django.urls import path
from . import views

urlpatterns = [
    path("producer/register/", views.producer_register, name="producer_register"),
    path("customer/register/", views.customer_register, name="customer_register"),
]
