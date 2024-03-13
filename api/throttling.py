from rest_framework.exceptions import Throttled
from rest_framework.throttling import (
    BaseThrottle, AnonRateThrottle, UserRateThrottle
)
from .multitoken.tokens_auth import MultiToken
from api.utils import SUBSCRIBED_ROLES

class CatvUsageExceededThrottle(BaseThrottle):
    throttled_error_msg = "You have exhausted your CATV usage credits. Please wait for your credits to be refilled."
    def allow_request(self, request, view):
        try:
            user_details, verified_token = MultiToken.get_user_from_key(request)
            usage = user_details['usage']
            role_name = user_details['role_details'][1]
            if role_name and role_name in SUBSCRIBED_ROLES:
                if (usage['subscribed_user_calls'] > 0):
                    return True
                else:
                    raise Throttled(detail=(self.throttled_error_msg))
            elif usage["catv"] > 0:
                return True
            else:
                raise Throttled(detail=(self.throttled_error_msg))


        except Exception as e:
            print(e.__str__())
            raise Throttled(detail=(self.throttled_error_msg))

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