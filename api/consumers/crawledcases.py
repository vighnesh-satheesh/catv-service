import json
import traceback

from .. import utils
from ..cache import DefaultCache
from ..constants import Constants
from ..models import CaseStatus, CaseHistory
from ..serializers import CaseTRDBSerializer
from api.internal.serializers import CasePostSerializer
from api.models import ConsumerErrorLogs
from api.tasks import IndicatorESDocumentTask


__all__ = ('process_crawled_cases',)


def process_crawled_cases(message):
    request_body = json.loads(message.value.decode("utf-8"))
    print("Processing message:\n")
    print(request_body)
    try:
        serializer = CasePostSerializer(data=request_body)
        serializer.is_valid(raise_exception=True)
        case = serializer.save()

        # save history.
        history_log = Constants.HISTORY_LOG
        history_log[
            "msg"] = CaseStatus.RELEASED.value if case.status.value == CaseStatus.RELEASED.value else CaseStatus.NEW.value
        history_log["type"] = "status"

        CaseHistory.objects.create(
            case=case,
            log=json.dumps(history_log),
            initiator=case.reporter if case.reporter is not None else None
        )
        
        if case.status == CaseStatus.RELEASED:
            case_serializer = CaseTRDBSerializer(case)
            data = case_serializer.data
            utils.TRDB_CLIENT.push_case("activateCase", data)

        # Update common redis cache for indicator, case count
        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])

        # Update Elasticsearch index
        IndicatorESDocumentTask(action=Constants.INDEX_ACTIONS["INDEX"]).run(case=case)
    except Exception as e:
        error_trace = traceback.format_exc()
        print(error_trace)
        ConsumerErrorLogs.objects.create(
            topic=message.topic,
            message=request_body,
            error_trace=error_trace
        )
