from django.urls import path
from . import views
from .views import address_search

urlpatterns = [
    path("producer/register/", views.producer_register, name="producer_register"),
    path("customer/register/", views.customer_register, name="customer_register"),
    path("api/address-search/", address_search, name="address_search"),

]
