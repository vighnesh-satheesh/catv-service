from .base import *
import environ

env = environ.Env()

DEBUG = False

ALLOWED_HOSTS += ['10.70.{}.{}'.format(i, j)
                  for i in range(256) for j in range(256)]
ALLOWED_HOSTS += ['172.16.144.{}'.format(i)
                  for i in range(256)]
ALLOWED_HOSTS += ['172.16.6.{}'.format(i)
                  for i in range(256)]
ALLOWED_HOSTS += [
    "localhost", "test.sentinelportal.com", "gcp-catv-service.api.sentinelprotocol.io", "gcp-portal.api.sentinelprotocol.io", "gcp-portal.sentinelprotocol.io", ".sentinelprotocol.io", "gcp-catv.api.sentinelprotocol.io"
]

# TODO: version file or tag?
version = env.str('PORTAL_API_VERSION', None)

INSTALLED_APPS = [
                     'elasticapm.contrib.django',
                     'django.contrib.admin',
                 ] + INSTALLED_APPS

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
    'SERVICE_NAME': env.str('API_APM_SERVICE_NAME', 'portal-catv-service'),
    # Set custom APM Server URL (default: http://localhost:8200)
    'SERVER_URL': env.str('API_ELASTIC_SERVER_URL', ''),
    'SECRET_TOKEN': env.str('API_APM_SECRET', ''),
    'ENVIRONMENT': env.str('CATVMS_API_ENV', '')
}

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
            'tags': ['django.request', 'django-portal-catv'],
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

CORS_ALLOW_ALL_ORIGINS = False
