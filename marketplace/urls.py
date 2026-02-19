from django.urls import path
from . import views

# Namespacing to avoid conflicts if diff apps have same url name.
app_name = 'marketplace'

urlpatterns = [ # If a request comes to this url, call this view function.
    path('', views.product_list, name='product_list'),
]