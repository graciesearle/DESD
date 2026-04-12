from rest_framework.permissions import BasePermission

from accounts.permissions import is_authenticated_with_role


class IsAIEngineerOrAdmin(BasePermission):
    message = "Only AI engineers or administrators can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(request, "AI_ENGINEER", "ADMIN")
