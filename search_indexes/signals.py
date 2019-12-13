from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django_elasticsearch_dsl.registries import registry

from api.models import Case


@receiver([post_save, post_delete], sender=Case)
def update_indicator_document(sender, instance: Case, created: bool, **kwargs: dict) -> None:
    """
    Update indicator document if a case is updated.
    E.g., related case status has changed.
    :param sender: Model class activity due to which the signal was invoked
    :param instance: Model instance
    :param created: Was a new record created?
    :param kwargs: Any additional arguments which can be used in this function
    :return: None. Update the elasticsearch registry for related indicators
    """
    indicator_instances = instance.indicators.all()
    for __instance in indicator_instances:
        registry.update(__instance)
