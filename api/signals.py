from datetime import timedelta

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.timezone import now

from .models import Key, OrganizationUser, Notification, NotificationType,\
    User, Usage, RoleUsageLimit, UserStatus


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


@receiver(post_save, sender=User)
def assign_usage_quota(sender, instance, created, **kwargs):
    """
    Insert record for api_usage credits when user
    is created and approved at the same time,
    e.g., when signing up through an OAuth2 provider
    :param sender: Model class activity due to which the signal was invoked
    :param instance: Model instance
    :param created: Was a new record created?
    :param kwargs: Any additional arguments which can be used in this function
    :return: None
    """
    if created and instance.status == UserStatus.APPROVED:
        try:
            current_user = instance
            user_role = RoleUsageLimit.objects.get(role=current_user.role)
            with transaction.atomic():
                Usage.objects.create(user=current_user, api_calls_left=user_role.api_limit,
                                     catv_calls_left=user_role.catv_limit, cara_calls_left=user_role.cara_limit,
                                     last_renewal_at=now())
                Key.objects.create(user=current_user, expire_datetime=now() + timedelta(days=30))
        except RoleUsageLimit.DoesNotExist:
            pass

