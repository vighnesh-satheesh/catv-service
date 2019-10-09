from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template
from api.models import EmailSent

class Email:
    def __init__(self):
        self.EMAIL_SENDER = {
            "NO-REPLY": "Sentinel Protocol Team <no-reply@sentinelprotocol.io>",
            "INFO": "Sentinel Protocol Team <info@sentinelprotocol.io>"
        }
        self.EMAIL_TYPE = {
            "REGISTER": "REGISTER",
            "VERIFICATION_RESEND": "VERIFICATION_RESEND",
            "VERIFIED": "VERIFIED",
            "PASSWORD_RESET": "PASSWORD_RESET",
            "NOTIFICATION": "NOTIFICATION",
            "INVITATION": "INVITATION"
        }
        self.EMAIL_TEMPLATE = {
            "REGISTER": {
                "text": "email/register.txt",
                "html": "email/register.html"
            },
            "VERIFICATION_RESEND": {
                "text": "email/register.txt",
                "html": "email/register.html"
            },
            "VERIFIED": {
                "text": "email/verified.txt",
                "html": "email/verified.html"
            },
            "PASSWORD_RESET": {
                "text": "email/passwordreset.txt",
                "html": "email/passwordreset.html"
            },
            "NOTIFICATION": {
                "text": "email/notification.txt",
                "html": "email/notification.html"
            },
            "INVITATION": {
                "text": "email/invitation.txt",
                "html": "email/invitation.html"
            }
        }

    def sendemail(self, *args, **kwargs):
        try:
            email_type = kwargs["email_type"]
            subject = kwargs["subject"]
            sender = kwargs["sender"]
            recipient = kwargs["recipient"]
        except KeyError:
            return False
        try:
            attachment = kwargs["attachment"]
        except KeyError:
            attachment = None
        try:
            kv = kwargs["kv"]
        except KeyError:
            kv = {}
        plaintext = get_template(self.EMAIL_TEMPLATE[email_type]["text"])
        htmly = get_template(self.EMAIL_TEMPLATE[email_type]["html"])
        text_content = plaintext.render(kv)
        html_content = htmly.render(kv)
        msg = EmailMultiAlternatives(subject, text_content, sender, recipient)
        msg.attach_alternative(html_content, "text/html")
        if attachment is not None:
            for att in attachment:
                msg.attach(att)
        msg.send()
        for r in recipient:
            email = EmailSent(
                type = email_type,
                email = r
            )
            email.save()
        return True
