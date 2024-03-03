import os
from .startup_util import set_environment_variables_from_secret_manager
from celery import Celery

env = os.environ.get("CATVMS_API_ENV")


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "portal_api.settings.{env}".format(env=env))

app = Celery("tasks")

app.config_from_object('django.conf:settings', namespace='CELERY')

set_environment_variables_from_secret_manager()

# discover and load tasks.py in django apps
app.autodiscover_tasks()

app.conf.update(
    accept_content=['json', 'pickle'],
    task_serializer='pickle',
    result_serializer='pickle'
)
