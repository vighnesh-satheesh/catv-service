
from rest_framework import permissions

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
