from django.urls import path
from . import views

# Namespacing to avoid conflicts if diff apps have same url name.
app_name = 'marketplace'

urlpatterns = [ # If a request comes to this url, call this view function.
    path('', views.product_list, name='product_list'),
    path('product/<int:pk>/', views.product_detail, name='product_detail'),
    path('add/', views.product_add, name='product_add'), 
    path('add-farm/', views.farm_add, name='farm_add'),

    # Producer product management
    path('edit/<int:pk>/', views.product_edit, name='product_edit'),
    path('toggle/<int:pk>/', views.product_toggle, name='product_toggle'),
    path('delete/<int:pk>/', views.product_delete, name='product_delete'),
    path('history/<int:pk>/', views.product_history, name='product_history'),

    # DRF API Endpoint
    path('api/products/', views.api_get_products, name='api_get_products'),
]