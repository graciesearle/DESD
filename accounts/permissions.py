from rest_framework.permissions import BasePermission


def is_authenticated_with_role(request, *roles):
    return (
        request.user
        and request.user.is_authenticated
        and request.user.role in roles
    )


class IsProducer(BasePermission):
    message = "Only producer accounts can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(request, "PRODUCER")


class IsCustomer(BasePermission):
    message = "Only customer accounts can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(
            request, "CUSTOMER", "COMMUNITY_GROUP", "RESTAURANT"
        )


class IsAdminUser(BasePermission):
    message = "Only administrators can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(request, "ADMIN")


class IsCommunityGroup(BasePermission):
    message = "Only community group accounts can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(request, "COMMUNITY_GROUP")


class IsRestaurant(BasePermission):
    message = "Only restaurant accounts can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(request, "RESTAURANT")


class IsProducerOrAdmin(BasePermission):
    message = "Only producer or administrator accounts can access this."

    def has_permission(self, request, view):
        return is_authenticated_with_role(request, "PRODUCER", "ADMIN")


class IsOwnerOrAdmin(BasePermission):
    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        if is_authenticated_with_role(request, "ADMIN"):
            return True
        if hasattr(obj, "user"):
            return obj.user == request.user
        if hasattr(obj, "producer"):
            return obj.producer == request.user
        return False
