from .base import *
import raven
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


# Sentry
# TODO: version file or tag?
version = env.str('PORTAL_API_VERSION', None)

RAVEN_CONFIG = {
    'dsn': env.str('API_SENTRY_DSN', None),
    'environment': env.str('SENTRY_ENVIRONMENT', 'Staging')
}

if version:
    RAVEN_CONFIG['release'] = version
