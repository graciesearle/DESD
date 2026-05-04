from django.urls import path
from . import views
from .views import address_search, CustomLoginView, custom_logout

urlpatterns = [
    path("producer/register/", views.producer_register, name="producer_register"),
    path("producer/onboarding/", views.producer_onboarding, name="producer_onboarding"),
    path("producer/dashboard/", views.producer_dashboard, name="producer_dashboard"),
    path("producer/reviews/", views.producer_reviews, name="producer_reviews"),
    path(
        "producer/reviews/<int:review_id>/respond/",
        views.producer_review_respond,
        name="producer_review_respond",
    ),
    path("customer/register/", views.customer_register, name="customer_register"),
    path("api/address-search/", address_search, name="address_search"),

    # Settings
    path("settings/", views.settings_view, name="settings"),
    path("settings/export/", views.export_user_data, name="export_data"),
    path("settings/deactivate/", views.deactivate_account, name="deactivate_account"),
    path("settings/unsubscribe/<int:producer_id>/", views.remove_subscription, name="remove_subscription"),

    # Secure Auth endpoints
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', views.custom_logout, name='logout'),

    # Stripe Connect
    path('stripe/connect/', views.stripe_connect, name='stripe_connect'),
    path('stripe/return/', views.stripe_return, name='stripe_return'),
    path('stripe/refresh/', views.stripe_refresh, name='stripe_refresh'),

    # Low stock notification settings
    path('settings/notifications/', views.update_notification_settings, name='update_notification_settings'),
]
