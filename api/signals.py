from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import OrganizationUser, Notification, NotificationType


@receiver(post_save, sender=OrganizationUser)
def create_org_notification(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(user=instance.user, initiator=instance.organization.administrator,
                                    type=NotificationType.ADDED_TO_ORG,
                                    target={
                                            "uid": str(instance.organization.uid),
                                            "title": "has added you to the organization {}, click here to view or exit "
                                                     "the organization".format(instance.organization.name),
                                            "type": "organization"
                                    })
