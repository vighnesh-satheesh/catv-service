from datetime import datetime

from dateutil.relativedelta import relativedelta
from rest_framework.throttling import (
    BaseThrottle, AnonRateThrottle, UserRateThrottle
)
from rest_framework.exceptions import Throttled

from .models import Usage, OrganizationUserStatus

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

class CATVInternalPostThrottle(AnonRateThrottle):
    scope = "catvInternalPost"

