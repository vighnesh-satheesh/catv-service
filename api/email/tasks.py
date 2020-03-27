from celery.task import Task
from celery.registry import tasks
from api.email import Email

class SendEmail(Task):
    def run(self, *args, **kwargs):
        email = Email()
        print("rec:", kwargs["recipient"])
        email.sendemail(
            kv = kwargs["kv"],
            subject = kwargs["subject"],
            email_type = kwargs["email_type"],
            sender = kwargs["sender"],
            recipient = kwargs["recipient"]
        )
        return True

tasks.register(SendEmail)
