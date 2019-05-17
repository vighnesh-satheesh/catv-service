from django.utils.translation import ugettext_lazy as _

from rest_framework import status
from rest_framework import exceptions


#####
# 400
#####

class ValidationError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Invalid input.')
    default_code = 'invalid'


class AuthenticationValidationError(ValidationError):
    default_detail = _('valid email and password are required.')


class EmailFormatError(ValidationError):
    default_detail = _('email is not valid')


class CaseFilterError(ValidationError):
    default_detail = _('not supported case filter.')


class CaseStatusChangeError(ValidationError):
    default_detail = _('{from_status} cannot be changed to {to_status}')

    def __init__(self, from_s, to_s):
        detail = self.default_detail.format(from_status=from_s, to_status=to_s)
        code = self.default_code

        super().__init__(detail, code)


class IndicatorDeleteError(ValidationError):
    default_detail = _('case should be in progress status.')


class FileNameTooLong(ValidationError):
    default_detail = _('the length of filename should be less than 255.')


class FileSizeTooSmall(ValidationError):
    default_detail = _('the size of file should be larger than 50 bytes.')

class ICFAlreadyExist(ValidationError):
    default_detail = _('icf api already exists.')

class PasswordResetCodeNotValid(ValidationError):
    default_detail = _('password reset code is not valid')

#####
# 401
#####

class AuthenticationCheckError(exceptions.AuthenticationFailed):
    default_detail = _('user not exist or password wrong.')


#####
# 404
#####

class UserNotFound(exceptions.NotFound):
    default_detail = _('user not found')


class CaseNotFound(exceptions.NotFound):
    default_detail = _('case not found')


class IndicatorNotFound(exceptions.NotFound):
    default_detail = _('indicator not found')


class ICONotFound(exceptions.NotFound):
    default_detail = _('ico not found')


class FileNotFound(exceptions.NotFound):
    default_detail = _('file not found')

class ICFNotFound(exceptions.NotFound):
    default_detail = _('api not found')

#####
# 403
#####

class NotAllowedError(exceptions.PermissionDenied):
    default_detail = _('no permission.')


class SupersentinelRequiredError(exceptions.PermissionDenied):
    default_detail = _('supersentinel permission required.')


class OwnerRequiredError(exceptions.PermissionDenied):
    default_detail = _('case owner required.')


class StatusChangeError(exceptions.PermissionDenied):
    default_detail = _('no access to change the status')


#####
# 409
#####

class DataIntegrityError(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _('data conflict')
