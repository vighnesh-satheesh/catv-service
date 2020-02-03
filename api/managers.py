"""
Put your custom managers here.
Let's say if you want to emit signals for certain methods,
which the Django ORM does not, e.g., for bulk create, bulk delete, etc.
or you want to override methods like get_queryset, etc.
"""
from django.db import models
from django.db.models.signals import post_save

__all__ = ('CustomManager',)


class CustomManager(models.Manager):
    """
    Manager class with overriden methods.
    """
    def bulk_create(self, items, **kwargs):
        """
        Modified bulk_create to trigger a post_save signal
        :param items: Model instance items
        :param kwargs: any additional arguments used during item creation
        :return: the bulk created model items
        """
        bulk_items = super().bulk_create(items, **kwargs)
        return bulk_items
