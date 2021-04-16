from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpRequest
from django.utils.timezone import now
from rest_framework.reverse import reverse

from .cache import DefaultCache
from .models import (
    Key, OrganizationUser, Notification, NotificationType,
    User, Usage, RoleUsageLimit, UserStatus,
    OrganizationUserStatus, Role, UserRoles, UserPermission,
    SecurityTag, CustomerSecurityTag
)


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
    else:
        if instance.status == OrganizationUserStatus.ACTIVE:
            User.objects.filter(id=instance.user_id).update(
                role=instance.organization.administrator.role,
                permission=instance.organization.administrator.permission
            )
        elif instance.status == OrganizationUserStatus.INACTIVE:
            User.objects.filter(id=instance.user_id).update(
                role=Role.objects.get(role_name=UserRoles.COMMUNITY.value),
                permission=UserPermission.USER.value
            )
            instance.delete()


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
            user_role = RoleUsageLimit.objects.using('default').get(role=current_user.role)
            with transaction.atomic():
                Usage.objects.create(user=current_user, api_calls_left=user_role.api_limit,
                                     catv_calls_left=user_role.catv_limit, cara_calls_left=user_role.cara_limit,
                                     cams_calls_left=user_role.cams_limit,
                                     last_renewal_at=now(), api_calls=0, catv_calls=0, cara_calls=0, cams_calls=0,
                                     api_calls_left_y=user_role.api_limit_y - user_role.api_limit,
                                     catv_calls_left_y=user_role.catv_limit_y - user_role.catv_limit,
                                     cara_calls_left_y=user_role.cara_limit_y - user_role.cara_limit,
                                     cams_calls_left_y=user_role.cams_limit_y - user_role.cams_limit,
                                     last_renewal_at_y=now())
                Key.objects.create(user=current_user, expire_datetime=now() + relativedelta(years=+99))
        except RoleUsageLimit.DoesNotExist:
            pass


@receiver(post_save, sender=SecurityTag)
def invalidate_tag_cache(sender, instance, created, **kwargs):
    request = HttpRequest()
    request.path = reverse('security-tags')
    c = DefaultCache()
    c.delete_view_cache(request)

@receiver(post_save, sender=CustomerSecurityTag)
def invalidate_c_tag_cache(sender, instance, created, **kwargs):
    request = HttpRequest()
    request.path = reverse('customer-tags')
    c = DefaultCache()
    c.delete_view_cache(request)
    