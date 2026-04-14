from django.urls import path
from . import views
from .views import address_search, CustomLoginView, custom_logout

urlpatterns = [
    path("producer/register/", views.producer_register, name="producer_register"),
    path("producer/dashboard/", views.producer_dashboard, name="producer_dashboard"),
    path("producer/reviews/", views.producer_reviews, name="producer_reviews"),
    path(
        "producer/reviews/<int:review_id>/respond/",
        views.producer_review_respond,
        name="producer_review_respond",
    ),
    path("customer/register/", views.customer_register, name="customer_register"),
    path("api/address-search/", address_search, name="address_search"),

    # Secure Auth endpoints
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.custom_logout, name='logout'),
]
