from django.shortcuts import render
from rest_framework import generics, permissions
from .models import Product
from .serializers import ProductSerializer


class IsProducer(permissions.BasePermission):
    """Only allow producers (or admins) to access the view."""
    def has_permission(self, request, view):
        return request.user.is_superuser or request.user.role == 'PRODUCER'


class IsProducerOwner(permissions.BasePermission):
    """Only let the producer who created a product edit/delete it."""
    def has_object_permission(self, request, view, obj):
        return obj.producer == request.user


class ProductListCreateView(generics.ListCreateAPIView):
    """GET = list producer's products, POST = create a new product."""
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, IsProducer]

    def get_queryset(self):
        return Product.objects.filter(producer=self.request.user)

    def perform_create(self, serializer):
        serializer.save(producer=self.request.user)  # auto-set producer


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PUT/PATCH = view/edit, DELETE = remove product."""
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, IsProducer, IsProducerOwner]

    def get_queryset(self):
        return Product.objects.filter(producer=self.request.user)