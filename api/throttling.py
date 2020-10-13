from datetime import datetime

from dateutil.relativedelta import relativedelta
from rest_framework.throttling import (
    BaseThrottle, AnonRateThrottle, UserRateThrottle
)
from rest_framework.exceptions import Throttled

from .models import Usage, OrganizationUserStatus


class EmailVerificationThrottle(UserRateThrottle):
    scope = "emailVerification"


class SignUpThrottle(UserRateThrottle):
    scope = "signup"


class UserLoginThrottle(AnonRateThrottle):
    scope = "userLogin"


class ChangePasswordThrottle(UserRateThrottle):
    scope = "changePassword"


class FileUploadThrottle(UserRateThrottle):
    scope = "fileUpload"


class CasePostThrottle(UserRateThrottle):
    scope = "casePost"


class IndicatorPostThrottle(UserRateThrottle):
    scope = "indicatorPost"


class CatvUsageExceededThrottle(BaseThrottle):
    def allow_request(self, request, view):
        org_details = request.user.organization_set.filter(organizationuser__status=OrganizationUserStatus.ACTIVE)
        if org_details.count():
            org = org_details.all()[0]
            usage_details = Usage.objects.values('catv_calls_left_y', 'last_renewal_at_y').\
                                filter(user=org.administrator)[0:1]
        else:
            usage_details = Usage.objects.values('catv_calls_left_y', 'last_renewal_at_y').\
                                filter(user_id=request.user.id)[0:1]

        if usage_details and usage_details[0]['catv_calls_left_y'] > 0:
            return True

        next_renewal_at = datetime.strftime(usage_details[0]['last_renewal_at_y'] + relativedelta(years=+1), '%Y-%m-%d')
        raise Throttled(detail=("You have exhausted your CATV usage credits. "
                                "Please wait until {} for your credits to be refilled.".format(next_renewal_at)))


class CatvNoThrottle(BaseThrottle):
    def allow_request(self, request, view):
        return True

class CatvPostThrottle(UserRateThrottle):
    scope = "catvPost"


class GuestSearchThrottle(UserRateThrottle):
    scope = "guestSearchGet"


"""
# login, changepassword api
class UserAuthenticationRateThrottle(SimpleRateThrottle):
    scope = 'userLoginAndChangePassword'

    def get_cache_key(self, request, view):
        user = User.objects.filter(email=request.data.get('email'))
        ident = user[0].pk if user else self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }

    def allow_request(self, request, view):
        if self.rate is None:
            return True

        self.key = self.get_cache_key(request, view)
        if self.key is None:
            return True

        self.history = self.cache.get(self.key, [])
        self.now = self.timer()

        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()

        if len(self.history) >= self.num_requests:
            return self.throttle_failure()

        if len(self.history) >= 3:
            data = Counter(self.history)
            for key, value in data.items():
                if value == 2:
                    return self.throttle_failure()
        return self.throttle_success(request)

    def throttle_success(self, request):
        user = User.objects.filter(email=request.data.get('email'))
        if user:
            self.history.insert(0, user[0].id)
        self.history.insert(0, self.now)
        self.cache.set(self.key, self.history, self.duration)
        return True
"""


class CaraUsageExceededThrottle(BaseThrottle):
    def allow_request(self, request, view):
        org_details = request.user.organization_set.filter(organizationuser__status=OrganizationUserStatus.ACTIVE)
        if org_details.count():
            org = org_details.all()[0]
            usage_details = Usage.objects.values('cara_calls_left_y', 'last_renewal_at_y').\
                                filter(user=org.administrator)[0:1]
        else:
            usage_details = Usage.objects.values('cara_calls_left_y', 'last_renewal_at_y').\
                            filter(user_id=request.user.id)[0:1]

        if usage_details and usage_details[0]['cara_calls_left_y'] > 0:
            return True

        next_renewal_at = datetime.strftime(usage_details[0]['last_renewal_at'] + relativedelta(years=+1), '%Y-%m-%d')
        raise Throttled(detail=("You have exhausted your CARA usage credits. "
                                "Please wait until {} for your credits to be refilled.".format(next_renewal_at)))


class CaraPostThrottle(UserRateThrottle):
    scope = "caraPost"


class CATVInternalPostThrottle(AnonRateThrottle):
    scope = "catvInternalPost"


class UpgradePlanThrottle(UserRateThrottle):
    scope = "upgradePostPut"


class UpgradePlanNoThrottle(BaseThrottle):
    def allow_request(self, request, view):
        return True
