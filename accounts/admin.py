from django.contrib import admin
from .models import CustomUser, ProducerProfile, CustomerProfile

from simple_history.admin import SimpleHistoryAdmin

@admin.register(CustomUser)
class CustomUserAdmin(SimpleHistoryAdmin):
    list_display = ('email', 'role', 'is_active', 'is_staff')
    list_filter = ('role', 'is_active')
    search_fields = ('email',)

# Registering the profiles just so they are accessible in admin
admin.site.register(ProducerProfile)
admin.site.register(CustomerProfile)