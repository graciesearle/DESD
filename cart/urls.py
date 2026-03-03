from django.urls import path
from . import views

app_name = 'cart'

urlpatterns = [
    path('', views.cart_detail, name='cart_detail'),

    # Cart API (JSON)
    path('api/add/', views.api_add_item, name='api_add_item'),
    path('api/update/<int:item_id>/', views.api_update_item, name='api_update_item'),
    path('api/remove/<int:item_id>/', views.api_remove_item, name='api_remove_item'),
]
