import os
from .startup_util import set_environment_variables_from_parameter_store, set_allowed_hosts


class AppInit:

    INIT_DONE = False

    def __new__(cls):
        if not hasattr(cls, 'instance') or not cls.instance:
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        env = os.environ.get("CATVMS_API_ENV")
        if env is None or env not in ["development", "production"]:
            raise AttributeError(
                "Missing environment variable 'CATVMS_API_ENV'."
                "CATVMS_API_ENV value should be either development or production."
            )
        if not self.INIT_DONE:
            set_allowed_hosts()
            set_environment_variables_from_parameter_store()
            self.INIT_DONE = True
            from .celery_app import app as celery_app


__all__ = ('celery_app',)