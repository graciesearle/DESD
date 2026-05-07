from django.urls import path
from . import views

app_name = "orders"

urlpatterns = [

    # Camunda REST Endpoints
    path("api/camunda/approve/", views.camunda_approve_order, name="camunda_approve"),
    path("api/camunda/alert-producer/", views.camunda_alert_producer, name="camunda_alert"),
    path("api/camunda/trigger-settlement/", views.camunda_trigger_settlement, name="camunda_trigger_settlement"),
    path("api/camunda/trigger-recurring/", views.camunda_trigger_recurring, name="camunda_trigger_recurring"),
    path("api/camunda/hide-review/", views.camunda_toggle_review, name="camunda_hide_review"),
    path("api/camunda/delete-review/", views.camunda_delete_review, name="camunda_delete_review"),
    path("api/camunda/surplus-notify/", views.camunda_surplus_notify, name="camunda_surplus_notify"),
    path("api/camunda/surplus-deactivate/", views.camunda_surplus_deactivate, name="camunda_surplus_deactivate"),
    path("api/camunda/check-stripe/", views.camunda_check_stripe, name="camunda_check_stripe"),
    path("api/camunda/stripe-reminder/", views.camunda_stripe_reminder, name="camunda_stripe_reminder"),
    path("api/camunda/check-order-status/", views.camunda_check_order_status, name="camunda_check_order_status"),
    path("api/camunda/cancel-pending-order/", views.camunda_cancel_pending_order, name="camunda_cancel_pending_order"),
    path("api/camunda/trigger-seasonal/", views.camunda_trigger_seasonal, name="camunda_trigger_seasonal"),


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
    path(
        "<str:order_number>/items/<int:item_id>/review/",
        views.create_review,
        name="create_review",
    ),

    # Recurring Order Management
    path("draft/<str:order_number>/", views.review_draft, name="review_draft"),
    path("producer/forecast/", views.producer_recurring_forecast, name="producer_recurring_forecast"),
    path("recurring/", views.recurring_management, name="recurring_management"),
    path("recurring/<int:template_id>/toggle/", views.toggle_recurring_template, name="toggle_recurring_template"),
    path("recurring/<int:template_id>/edit/", views.edit_recurring_template, name="edit_recurring_template"),
    path("recurring/<int:template_id>/cancel/", views.cancel_recurring_template, name="cancel_recurring_template"),

    # Producer status updates
    path("producer/sub-orders/<int:sub_order_id>/status/", views.producer_update_sub_order_status, name="producer_update_sub_order_status"),

    path("<str:order_number>/", views.order_detail, name="order_detail"),

]
