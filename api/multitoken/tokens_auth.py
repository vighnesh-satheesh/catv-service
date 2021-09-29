import json

from django.core.cache import caches
# from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication, get_authorization_header

from .crypto import generate_new_token, verify_token
from ..settings import api_settings
from ..exceptions import AuthenticationCheckError


TOKENS_CACHE = caches[api_settings.TOKEN_REDIS_DB_NAME]
USER_CACHE = caches[api_settings.API_USER_CACHE]


class MultiToken:

    def __init__(self, key, user):
        self.key = key
        self.user = user

    @classmethod
    def create_token(cls, user):
        created = False
        token = generate_new_token()
        tokens = TOKENS_CACHE.get(user.pk)

        if not tokens:
            tokens = [token]
            created = True
        else:
            tokens.append(token)

        cls._set_key_value(str(user.pk), tokens)
        cls._set_key_value(token, str(user.pk))

        return MultiToken(token, user), created

    @classmethod
    def get_user_from_key(cls, request):
        auth = get_authorization_header(request).split()
        token = auth[1].decode()
        timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)
        verified_token = verify_token(token, timestamp)
        user = USER_CACHE.get(verified_token)
        user_json = json.loads(user)
        # user_json = user
        # usage_details = user_json['usage']
        return user_json, verified_token

    @classmethod
    def _reset_token_ttl(cls, key):
        timeout = cls._get_user_provided_ttl()
        key_ttl = TOKENS_CACHE.ttl(key)

        if key_ttl is None and timeout is not None:
            if api_settings.TOKEN_OVERWRITE_NONE_TTL:
                TOKENS_CACHE.expire(key, timeout)
                USER_CACHE.expire(key, timeout)
        elif key_ttl is None and timeout is None:
            pass
        elif key_ttl is not None and timeout is None:
            TOKENS_CACHE.persist(key)
            USER_CACHE.persist(key)
        else:
            TOKENS_CACHE.expire(key, timeout)
            USER_CACHE.expire(key, timeout)

    @classmethod
    def _set_key_value(cls, key, value):
        timeout = cls._get_user_provided_ttl()
        TOKENS_CACHE.set(key, value, timeout=timeout)

    @classmethod
    def _get_user_provided_ttl(cls):
        return api_settings.TOKEN_EXPIRE_TIME


class CachedTokenAuthentication(TokenAuthentication):
    def authenticate(self, request):
        auth = get_authorization_header(request).split()

        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth) == 1:
            raise AuthenticationCheckError()
        elif len(auth) > 2:
            raise AuthenticationCheckError()

        try:
            token = auth[1].decode()
        except UnicodeError:
            raise AuthenticationCheckError()

        return self.authenticate_credentials(request)

    def authenticate_credentials(self, request):
        try:
            user, token = MultiToken.get_user_from_key(request)
            if api_settings.TOKEN_RESET_TTL_ON_USER_LOG_IN:
                # MultiToken.reset_tokens_ttl(user.pk)
                MultiToken._reset_token_ttl(token)
            if user["user_id"]:
                return (user, MultiToken(token, user))
            else:
                raise AuthenticationCheckError("invalid token")
        except Exception:
            raise AuthenticationCheckError("invalid token")

