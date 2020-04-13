from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from api.models import Case
from api.tasks import IndicatorESDocumentTask


# @receiver([post_save, post_delete], sender=Case)
# def update_indicator_document(sender, instance: Case, created: bool = False, **kwargs: dict) -> None:
#     """
#     Update indicator document if a case is updated.
#     E.g., related case status has changed.
#     :param sender: Model class activity due to which the signal was invoked
#     :param instance: Model instance
#     :param created: Was a new record created?
#     :param kwargs: Any additional arguments which can be used in this function
#     :return: None. Update the elasticsearch registry for related indicators
#     """
#     if not created:
#         IndicatorESDocumentTask().delay(case=instance)
