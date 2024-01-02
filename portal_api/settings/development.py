from .base import *


DEBUG = True

# CORS_ALLOW_ALL_ORIGINS = True
# ALLOWED_HOSTS += env.list('ALLOWED_HOSTS', default=['*', ])
ALLOWED_HOSTS += ['10.12.{}.{}'.format(i, j) for i in range(256) for j in range(256)]
ALLOWED_HOSTS += [
    "localhost", "test.sentinelportal.com", "stgcatv-service.api.sentinelprotocol.io", "stgportal.api.sentinelprotocol.io", "stgportal.sentinelprotocol.io", "stgcatv.api.sentinelprotocol.io"
]
ALLOWED_HOSTS += ["172.16.4.%s" % s for s in range(2, 255)]
ALLOWED_HOSTS += ["172.16.5.%s" % s for s in range(2, 255)]

ALLOWED_HOSTS += ['10.80.{}.{}'.format(i, j)
                  for i in range(256) for j in range(256)]
ALLOWED_HOSTS += ['172.16.{}.{}'.format(i, j)
                  for i in range(128, 143) for j in range(256)]


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.staticfiles'
] + INSTALLED_APPS


INSTALLED_APPS += [
    'debug_toolbar',
    'rest_framework_swagger',
]


MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware', ]


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = env.str('STATIC_ROOT', './static/')


# Debug toolbar setting

DEBUG_TOOLBAR_CONFIG = {
    'SHOW_COLLAPSED': True,
    'SQL_WARNING_THRESHOLD': 300
}

INTERNAL_IPS = ["127.0.0.1", ]


SWAGGER_SETTINGS = {
    'USE_SESSION_AUTH': False,
    'LOGIN_URL': None,
    'LOGOUT_URL': None,
}
