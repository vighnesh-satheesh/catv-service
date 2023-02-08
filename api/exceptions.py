from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework import exceptions


#####
# 400
#####


class ValidationError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Invalid input.')
    default_code = 'invalid'


#####
# 401
#####


class AuthenticationCheckError(exceptions.AuthenticationFailed):
    default_detail = _('user not exist or password wrong.')


#####
# 404
#####

class FileNotFound(exceptions.NotFound):
    default_detail = _('file not found')

class CATVReportNotFound(exceptions.NotFound):
    default_detail = _('CATV Report not found')


#####
# 403
#####


class NotAllowedError(exceptions.PermissionDenied):
    default_detail = _('no permission.')


#####
# 409
#####


class DataIntegrityError(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _('data conflict')

class ServerError(exceptions.APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = _('Something went wrong')
