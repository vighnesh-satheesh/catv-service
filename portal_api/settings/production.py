from .base import *
import environ

env = environ.Env()

DEBUG = False

ALLOWED_HOSTS += env.list('ALLOWED_HOSTS', default=['*', ])

# For ElasticSearch logging
"""
Most probably we don't need to change the middleware on the next line,
because Elastic APM inserts the APM middleware to the top of the middleware list by default
https://www.elastic.co/guide/en/apm/agent/python/current/configuration.html#config-django-autoinsert-middleware
Just to be double sure if the build fails
"""
MIDDLEWARE.insert(0, 'elasticapm.contrib.django.middleware.TracingMiddleware')
ELASTIC_APM = {
    # Set required service name. Allowed characters:
    # a-z, A-Z, 0-9, -, _, and space
    'SERVICE_NAME': env.str('API_APM_SERVICE_NAME', ''),
    # Set custom APM Server URL (default: http://localhost:8200)
    'SERVER_URL': env.str('API_ELASTIC_SERVER_URL', ''),
}

ELASTICSEARCH_INDEX_NAMES = {
    'search_indexes.documents.role': env.str('API_ELASTIC_ROLE_IDX', 'role'),
    'search_indexes.documents.user': env.str('API_ELASTIC_USER_IDX', 'user'),
    'search_indexes.documents.case': env.str('API_ELASTIC_CASE_IDX', 'case'),
    'search_indexes.documents.indicator': env.str('API_ELASTIC_INDICATOR_IDX', 'indicator'),
}

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
