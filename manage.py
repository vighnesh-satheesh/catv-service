#!/usr/bin/env python
import logging
import os
import sys

from celery.signals import after_setup_logger, after_setup_task_logger
import logstash

from portal_api import AppInit


def setup_logstash_celery(logger=None, loglevel=logging.DEBUG, **kwargs):
    handler = logstash.TCPLogstashHandler(os.environ.get('API_LOGSTASH_SERVER', 'localhost'), 5959, tags=['celery'])
    handler.setLevel(loglevel)
    logger.addHandler(handler)
    return logger


if __name__ == "__main__":
    AppInit()
    after_setup_task_logger.connect(setup_logstash_celery)
    after_setup_logger.connect(setup_logstash_celery)
    env = os.environ.get("CATVMS_API_ENV")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "portal_api.settings.{env}".format(env=env))
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)
