from django.apps import AppConfig, apps
from celery import Celery
from django.conf import settings
from .cache import DefaultCache
from django.conf import settings
import requests
import json
import os

class ApiConfig(AppConfig):
    name = 'api'
    verbose_name = "ApiConfig"
    app = Celery('tasks')
    app.config_from_object('django.conf:settings')
    app.autodiscover_tasks(lambda: [n.name for n in apps.get_app_configs()])

    @classmethod
    def init_cache(cls, user_model):
        c = DefaultCache()
        users = user_model.objects.all()
        for u in users:
            key = "user_" + str(u.pk)
            c.set(key, u, 0)

    @classmethod
    def send_slack_webhook(cls):
        if settings.ENVIRONMENT == "development" and os.environ.get("CONTAINER_TYPE") == "portal_api":
            return True
        if os.environ.get("CONTAINER_TYPE") == "portal_admin":
            data = {
                "text": "PORTAL ADMIN " + settings.ALLOWED_HOSTS[0] + " is ready."
            }
        else:
            data = {
                "text": "PORTAL API " + settings.API_SETTINGS["WEB_URL"] + " is ready."
            }
        r = requests.post(
            "https://hooks.slack.com/services/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",
            data=json.dumps(data),
            headers={
                "Content-Type": "application/json"
            }
        )

    def ready(self):
        self.init_cache(self.get_model('User'))
        self.send_slack_webhook()
        from api.scheduler import kafkascheduler
        kafkascheduler.start()
        import api.signals

