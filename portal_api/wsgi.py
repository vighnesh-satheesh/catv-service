"""
WSGI config for portal_api project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/howto/deployment/wsgi/
"""

import os
from . import AppInit
from django.core.wsgi import get_wsgi_application
AppInit()
env = os.environ.get("CATVMS_API")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "portal_api.settings.{env}".format(env=env))
application = get_wsgi_application()
