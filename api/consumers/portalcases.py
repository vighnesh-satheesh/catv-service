import json
import traceback

from ..constants import Constants
from ..models import Case, Indicator
from api.models import ConsumerErrorLogs
from api.tasks import IndicatorESDocumentTask

__all__ = ('process_portal_cases',)


def process_portal_cases(message):
    request_body = json.loads(message.value.decode("utf-8"))
    print("Processing message:\n")
    print(request_body)
    try:
        action_type = request_body.get("action_type", None)
        if action_type == Constants.CASE_ACTIONS["CREATE"]:
            case = Case.objects.get(id=request_body.get("related_ids", None))
            IndicatorESDocumentTask(action=Constants.INDEX_ACTIONS["INDEX"]).run(case=case)
        elif action_type == Constants.CASE_ACTIONS["UPDATE"]:
            case = Case.objects.get(id=request_body.get("related_ids", None))
            IndicatorESDocumentTask(action=Constants.INDEX_ACTIONS["UPDATE"]).run(case=case)
        elif action_type == Constants.CASE_ACTIONS["DELETE"]:
            indicators = Indicator.objects.filter(id__in=request_body.get("related_ids", None))
            print(indicators)
            IndicatorESDocumentTask(action=Constants.INDEX_ACTIONS["UPDATE"]).run(indicators=indicators)
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        ConsumerErrorLogs.objects.create(
            topic=message.topic,
            message=request_body,
            error_trace=error_trace
        )
