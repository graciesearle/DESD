from django.db import models
from django.utils import timezone

class SoftDeleteManager(models.Manager):
    """Only returns objects that have not been soft-deleted."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def all_with_deleted(self):
        """Use this if the Admin needs to see everything, including deleted items."""
        return super().get_queryset()

class SoftDeleteModel(models.Model):
    """
    Abstract Base class providing soft-delete functionality.
    Other apps can import this to ensure audit trails are kept.
    """
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager() # Default manager hides deleted items
    all_objects = models.Manager() # Secondary manager shows everything (for audit)

    class Meta:
        abstract = True # Tells Django not to create a database table for this specific class.
    
    def delete(self, *args, **kwargs):
        """Revamps delete to mark as deleted instead of removing from DB."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self, *args, **kwargs):
        """Actual Database Deletion (for emergencies or any GDPR compliance)"""
        super().delete(*args, **kwargs)