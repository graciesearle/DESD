from rest_framework.permissions import BasePermission

from accounts.permissions import is_authenticated_with_role


class IsAIEngineerOrAdmin(BasePermission):
    message = "Only AI engineers or administrators can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(request, "AI_ENGINEER", "ADMIN")


class IsExportOwnerOrAdmin(BasePermission):
    message = "Only the export owner or an administrator can view this export job."

    def has_object_permission(self, request, view, obj):
        if is_authenticated_with_role(request, "ADMIN"):
            return True
        return obj.requested_by_id == request.user.id
