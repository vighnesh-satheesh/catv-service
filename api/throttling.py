from datetime import datetime

from dateutil.relativedelta import relativedelta
from rest_framework.throttling import (
    BaseThrottle, AnonRateThrottle, UserRateThrottle
)
from rest_framework.exceptions import Throttled

from .multitoken.tokens_auth import MultiToken
from .models import Usage, OrganizationUserStatus

class CatvUsageExceededThrottle(BaseThrottle):
    def allow_request(self, request, view):
        try:
            user_details, verified_token = MultiToken.get_user_from_key(request)
            usage = user_details['usage']
            if usage["catv"] > 0:
                print("UID:", user_details['user_uid'])
                return True
            else:
                raise Throttled(detail=("You have exhausted your CATV usage credits. "
                                        "Please wait for your credits to be refilled."))

        except Exception as e:
            print(e.__str__())
            raise Throttled(detail=("You have exhausted your CATV usage credits. "
                                    "Please wait for your credits to be refilled."))

class CatvNoThrottle(BaseThrottle):
    def allow_request(self, request, view):
        return True

class CatvPostThrottle(UserRateThrottle):
    scope = "catvPost"

    def get_cache_key(self, request, view):
        user_details, verified_token = MultiToken.get_user_from_key(request)
        if user_details['is_authenticated']:
            ident = user_details['user_id']
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }

class CATVInternalPostThrottle(AnonRateThrottle):
    scope = "catvInternalPost"

    def get_cache_key(self, request, view):
        user_details, verified_token = MultiToken.get_user_from_key(request)
        if user_details['is_authenticated']:
            ident = user_details['user_id']
        else:
            ident = self.get_ident(request)

        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }

