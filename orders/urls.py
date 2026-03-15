from django.urls import path
from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.checkout, name="checkout"),
    path("confirmation/<str:order_number>/", views.order_confirmation, name="order_confirmation"),
    path("", views.order_list, name="order_list"),

    # API must come before the catch-all <str:order_number> route,
    # otherwise Django matches "api" as an order number and returns 404.
    path("api/", views.ProducerOrderListAPIView.as_view(), name="api_producer_orders"),


    #Stripe calls if success or fail
    path("payment/success/", views.payment_success, name="payment_success"),
    path("payment/cancel/", views.payment_cancel, name="payment_cancel"),

    #producer payouts
    path("payouts/", views.producer_payouts, name="producer_payouts"),
    path("payouts/csv/", views.producer_payouts_csv, name="producer_payouts_csv"),
    path("payouts/pdf/", views.producer_payouts_pdf, name="producer_payouts_pdf"),

    path("<str:order_number>/", views.order_detail, name="order_detail"),

]
