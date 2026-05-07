from django.urls import path
from . import views
from .views_admin_moderation import (
    admin_review_moderation,
    admin_moderate_review,
    admin_moderate_response,
    admin_bulk_moderate,
    admin_review_detail,
    admin_moderate_comment,
)

# Namespacing to avoid conflicts if diff apps have same url name.
app_name = 'marketplace'

urlpatterns = [ # If a request comes to this url, call this view function.
    path('', views.product_list, name='product_list'),
    path('product/<int:pk>/', views.product_detail, name='product_detail'),
    path('product/<int:pk>/reviews/<int:review_id>/delete/', views.delete_own_review, name='delete_own_review'),
    path('add/', views.product_add, name='product_add'), 
    path('add-farm/', views.farm_add, name='farm_add'),

    # Producer product management
    path('edit/<int:pk>/', views.product_edit, name='product_edit'),
    path('toggle/<int:pk>/', views.product_toggle, name='product_toggle'),
    path('delete/<int:pk>/', views.product_delete, name='product_delete'),
    path('history/<int:pk>/', views.product_history, name='product_history'),

    # Community
    path('community/', views.community_feed, name='community_feed'),
    path('producers/', views.producer_directory, name='producer_directory'),
    path('producers/<int:producer_id>/profile/', views.producer_profile, name='producer_profile'),
    path('producers/<int:producer_id>/subscribe/', views.toggle_subscription, name='toggle_subscription'),
    path('producer/post/new/', views.create_educational_post, name='create_educational_post'),
    path('producer/post/edit/<int:pk>/', views.edit_educational_post, name='edit_educational_post'),
    path('producer/post/delete/<int:pk>/', views.delete_educational_post, name='delete_educational_post'),
    path('post/<int:post_id>/like/', views.toggle_post_like, name='toggle_post_like'),

    # Search bar suggestions API Endpoint
    path('search/suggestions/', views.search_suggestions, name='search_suggestions'),

    # Recipes
    path('producer/recipe/new/', views.create_recipe, name='create_recipe'),
    path('producer/recipe/edit/<int:pk>/', views.edit_recipe, name='edit_recipe'),
    path('producer/recipe/delete/<int:pk>/', views.delete_recipe, name='delete_recipe'),
    path('recipe/<int:pk>/', views.recipe_detail, name='recipe_detail'),
    path('recipe/<int:pk>/save/', views.toggle_saved_recipe, name='toggle_saved_recipe'),

    # ── Admin Review Moderation Dashboard ──
    path('admin/reviews/', admin_review_moderation, name='admin_review_moderation'),
    path('admin/reviews/<int:review_id>/moderate/', admin_moderate_review, name='admin_moderate_review'),
    path('admin/reviews/<int:review_id>/moderate-response/', admin_moderate_response, name='admin_moderate_response'),
    path('admin/reviews/<int:review_id>/detail/', admin_review_detail, name='admin_review_detail'),
    path('admin/reviews/bulk/', admin_bulk_moderate, name='admin_bulk_moderate'),
    path('admin/comments/<int:comment_id>/moderate/', admin_moderate_comment, name='admin_moderate_comment'),

    # Comments
    path('post/<int:post_id>/comment/', views.add_post_comment, name='add_post_comment'),
    path('recipe/<int:pk>/comment/', views.add_recipe_comment, name='add_recipe_comment'),
    path('comment/<int:comment_id>/reply/', views.reply_to_comment, name='reply_to_comment'),
    path('comment/<int:comment_id>/delete/', views.delete_comment, name='delete_comment'),
    
    # Surplus Deals
    path('product/<int:pk>/mark-surplus/', views.mark_as_surplus, name='mark_as_surplus'),
    path('product/<int:pk>/remove-surplus/', views.remove_surplus, name='remove_surplus'),

]