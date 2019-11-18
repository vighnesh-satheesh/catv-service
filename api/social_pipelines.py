"""
Overridden functions which can be used to extend or modify
the default pipelines from Python Social Auth (PSA).
See the `SOCIAL_AUTH_PIPELINE` setting in base.py to
understand the flow of pipelines in PSA.
"""
import re

from .utils import generate_random_key
from .models import User, Role, UserPermission, UserStatus, UserRoles

USER_FIELDS = ['email', 'password', 'nickname', 'permission', 'status', 'role']
NO_ASCII_REGEX = re.compile(r'[^\x00-\x7F]+')
NO_SPECIAL_REGEX = re.compile(r'[^\w.@+_-]+', re.UNICODE)


def get_username(strategy, details, backend, user=None, *args, **kwargs):
    """
    Return the username as the email.
    If the user does not exist, later on we will create it in `create_user`
    :param strategy: Storage strategy, e.g. Django ORM, Mongoengine
    :param details: Details returned by the OAuth2 provider. Typically just the email and name
    :param backend: OAuth2 provider backend, e.g. Google, Facebook, Twitter
    :param user: Model user object
    :param args: Positional arguments such as `extra_data`
    :param kwargs: Any other keyword arguments which can be used by storage strategy
    :return: username
    """
    final_username = details['email']
    return {'username': final_username}


def create_user(strategy, details, backend, user=None, *args, **kwargs):
    """
    Create user if it does not exist.
    Processed through the Django ORM.
    :param strategy: Storage strategy, e.g. Django ORM, Mongoengine
    :param details: Details returned by the OAuth2 provider. Typically just the email and name
    :param backend: OAuth2 provider backend, e.g. Google, Facebook, Twitter
    :param user: Model user object
    :param args: Positional arguments such as `extra_data`
    :param kwargs: Any other keyword arguments which can be used by storage strategy
    :return: dictionary with key values indicating if the user exists.
    If not then an extra user key with the created user object.
    """
    if user:
        return {'is_new': False}

    email_username = "".join(details['email'].split('@')[:-1])
    email_username = NO_ASCII_REGEX.sub('', email_username)
    email_username = NO_SPECIAL_REGEX.sub('', email_username)

    fields = dict((name, kwargs.get(name, details.get(name, None)))
                  for name in backend.setting('USER_FIELDS', USER_FIELDS))
    fields['nickname'] = email_username + '_' + generate_random_key(5)
    fields['password'] = generate_random_key(16)
    fields['permission'] = UserPermission.USER.value
    fields['status'] = UserStatus.APPROVED.value
    fields['role'] = Role.objects.get(role_name=UserRoles.COMMUNITY.value)

    return {
        'is_new': True,
        'user': User.objects.create(**fields)
    }
