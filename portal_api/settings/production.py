from .base import *
import environ

env = environ.Env()

DEBUG = False
CORS_ORIGIN_ALLOW_ALL = True
ALLOWED_HOSTS += env.list('ALLOWED_HOSTS', default=['*', ])

# Sentry
# TODO: version file or tag?
version = env.str('PORTAL_API_VERSION', None)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'logstash': {
            'level': 'WARNING',
            'class': 'logstash.TCPLogstashHandler',
            'host': env.str('API_LOGSTASH_SERVER', 'localhost'),
            'port': 5959,
            'version': 1,
            'message_type': 'logstash',
            'fqdn': True,
            'tags': ['django.request', 'django-portalapi'],
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'propagate': True,
        },
        'django.request': {
            'handlers': ['logstash'],
            'level': 'WARNING',
            'propagate': False
        },
    }
}
