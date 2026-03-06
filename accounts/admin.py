from django.contrib import admin
from accounts.models import CustomUser, ProducerProfile, CustomerProfile, AdminProfile

admin.site.register(CustomUser)
admin.site.register(ProducerProfile)
admin.site.register(CustomerProfile)
admin.site.register(AdminProfile)