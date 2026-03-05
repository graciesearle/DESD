from django.urls import path
from . import views
from .views import address_search, CustomLoginView, custom_logout

urlpatterns = [
    path("producer/register/", views.producer_register, name="producer_register"),
    path("customer/register/", views.customer_register, name="customer_register"),
    path("api/address-search/", address_search, name="address_search"),

    # Secure Auth endpoints
    path('login/', CustomLoginView.as_view(), name='login'), # .as_view converts class into callable function
    path('logout/', custom_logout, name='logout'),
]
