from django.urls import path
from . import views

# Namespacing to avoid conflicts if diff apps have same url name.
app_name = 'marketplace'

urlpatterns = [ # If a request comes to this url, call this view function.
    path('', views.product_list, name='product_list'),
    path('add/', views.product_add, name='product_add'), 

    # DRF API Endpoint
    path('api/products/', views.api_get_products, name='api_get_products'),
]