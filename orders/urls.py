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

    # Admin Commissions
    path("admin-commissions/", views.admin_commissions, name="admin_commissions"),
    path("admin-commissions/export/", views.admin_commissions_csv, name="admin_commissions_csv"),
    path("admin-commissions/export/accounting/", views.admin_commissions_accounting_csv, name="admin_commissions_accounting_csv"),
    path("admin-commissions/<str:order_number>/", views.admin_commissions_detail, name="admin_commissions_detail"),

    #producer payouts
    path("payouts/", views.producer_payouts, name="producer_payouts"),
    path("payouts/csv/", views.producer_payouts_csv, name="producer_payouts_csv"),
    path("payouts/pdf/", views.producer_payouts_pdf, name="producer_payouts_pdf"),

    # Notification Alerts
    path("notifications/", views.notifications_list, name="notifications"),

    # Customer order history actions
    path("<str:order_number>/reorder/", views.reorder_order, name="reorder_order"),
    path("<str:order_number>/receipt/", views.download_receipt, name="download_receipt"),
    # Producer status updates
    path("producer/sub-orders/<int:sub_order_id>/status/", views.producer_update_sub_order_status, name="producer_update_sub_order_status"),

    path("<str:order_number>/", views.order_detail, name="order_detail"),

]
