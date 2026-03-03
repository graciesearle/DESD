from django.contrib import admin


class SoftDeleteAdmin(admin.ModelAdmin):
    """
    Admin base class for soft-deletable models.
    Overrides the default queryset so admins can see all records,
    including those that have been soft-deleted.
    """
    def get_queryset(self, request):
        return self.model.all_objects.all()
