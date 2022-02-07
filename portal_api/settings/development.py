from .base import *


DEBUG = True

CORS_ORIGIN_ALLOW_ALL = True
ALLOWED_HOSTS += ["172.21.20.%s" % s for s in range(2, 255)]
ALLOWED_HOSTS += ["10.12.49.%s" % s for s in range(2, 255)]
ALLOWED_HOSTS += ["10.12.50.%s" % s for s in range(2, 255)]
ALLOWED_HOSTS += [
    "localhost", "test.sentinelportal.com", "stgcatv-service.api.sentinelprotocol.io", "stgportal.sentinelprotocol.io"
]

ALLOWED_HOSTS += env.list('ALLOWED_HOSTS', default=['*', ])

# ALLOWED_HOSTS = ['*', ]


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

# CORS_ORIGIN_ALLOW_ALL = True