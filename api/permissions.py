from rest_framework import permissions
from .settings import api_settings
from .models import (
    UserPermission, CaseStatus
)

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS and (request.user and request.user.is_authenticated):
            return True

        # Write permissions are only allowed to the owner of the snippet.
        return obj.owner == request.user


class IsPostOrIsAuthenticated(permissions.BasePermission):

    def has_permission(self, request, view):
        if request.method == "POST":
            return True
        return request.user and request.user.is_authenticated


class InternalOnly(permissions.BasePermission):

    def has_permission(self, request, view):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        if ip.startswith("127") or ip.startswith("10.") or ip.startswith("172.") or ip.startswith("192.") or ip.startswith("255."):
            return True
        return False


class CheckCaseDetailPermission(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request and not request.user:
            return False

        if request.user.permission in [UserPermission.SENTINEL, UserPermission.SUPERSENTINEL]:
            return True
        else:
            if obj.reporter == request.user:
                return True
            elif request.user.permission is UserPermission.EXCHANGE and obj.status in [CaseStatus.CONFIRMED, CaseStatus.RELEASED]:
                return True
            else:
                return False


class CaseListPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        full_path = request.get_full_path()
        full_path = full_path.split('&')[0]

        if request.method == "POST" and full_path == '/case':
            return True

        if not request and not request.user:
            return False

        if request.user.permission in [UserPermission.SENTINEL, UserPermission.SUPERSENTINEL]:
            return True

        if full_path in ['/case?case=my', '/case?case=my_new', '/case?case=my_progress', '/case?case=my_confirmed', '/case?case=my_rejected', '/case?case=my_released']:
            return True
        if request.user.permission is UserPermission.EXCHANGE and full_path in ['/case?case=all', '/case?case=all_confirmed', '/case?case=all_released']:
            return True

        return False
