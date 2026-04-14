from rest_framework import serializers
from .models import CustomUser, ProducerProfile, CustomerProfile


class BaseUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'id',
            'email',
            'role',
            'phone',
            'date_joined',
            'is_active',
        ]
        read_only_fields = ['id', 'date_joined']


class ProducerProfileSerializer(serializers.ModelSerializer):
    user = BaseUserSerializer(read_only=True)
    full_address = serializers.ReadOnlyField()

    class Meta:
        model = ProducerProfile
        fields = [
            'id',
            'user',
            'business_name',
            'contact_name',
            'address',
            'postcode',
            'full_address',
            'lead_time_hours',
            'organic_certified',
            'certification_body',
            'bank_sort_code',
            'bank_account_number',
            'tax_reference',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CustomerProfileSerializer(serializers.ModelSerializer):
    user = BaseUserSerializer(read_only=True)
    display_name = serializers.ReadOnlyField()

    class Meta:
        model = CustomerProfile
        fields = [
            'id',
            'user',
            'full_name',
            'customer_type',
            'organisation_name',
            'delivery_address',
            'postcode',
            'receive_surplus_alerts',
            'display_name',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']