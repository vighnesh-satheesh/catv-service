import json
from operator import gt, lt
from uuid import UUID

from api.catvutils.metrics import CatvMetrics
from api.exceptions import FileNotFound
from api.models import (
    CatvTokens, CatvSearchType,
    CatvRequestStatus, CatvTaskStatusType,
    ConsumerErrorLogs
)
from api.serializers import (
    CATVSerializer, CATVBTCCoinpathSerializer,
    CatvBtcPathSerializer, CATVEthPathSerializer
)
from api.tasks import CatvHistoryTask

__all__ = ('process_catv_messages',)


def process_catv_messages(message):
    request_body = json.loads(message.value.decode("utf-8"))
    print("Processing message:\n")
    print(request_body)

    serializer_map = {
        CatvTokens.ETH.value: {
            CatvSearchType.FLOW.value: CATVSerializer,
            CatvSearchType.PATH.value: CATVEthPathSerializer
        },
        CatvTokens.BTC.value: {
            CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
            CatvSearchType.PATH.value: CatvBtcPathSerializer
        }
    }

    try:
        results = None
        message_id = UUID(request_body["message_id"])
        user_id = request_body["user_id"]
        token_type = request_body.get("token_type", CatvTokens.ETH.value)
        search_type = request_body.get("search_type", CatvSearchType.FLOW.value)
        search_params = request_body.get("search_params", {})
        serializer_obj = serializer_map[token_type][search_type](data=search_params)
        serializer_obj.is_valid(raise_exception=True)
        core_results = serializer_obj.get_tracking_results(save_to_db=False)
        catv_metrics = CatvMetrics(core_results.get("graph", {}))
        dist_analysis = {}
        src_analysis = {}
        if search_params.get("distribution_depth", 0) > 0:
            dist_analysis = catv_metrics.generate_metrics(gt)
        if search_params.get("source_depth", 0) > 0:
            src_analysis = catv_metrics.generate_metrics(lt)
        catv_metrics.save_annotations()
        results = {
            "data": {
                **core_results["graph"],
                "dist_analysis": dist_analysis,
                "src_analysis": src_analysis
            },
            "messages": {**core_results["messages"]}
        }
        search_params.update({'user_id': user_id, 'token_type': token_type})
        CatvHistoryTask().run(history=search_params, from_history=True)
        task_status = CatvTaskStatusType.RELEASED
    except Exception as e:
        error_trace = str(e)
        print(error_trace)
        generic_error = "Internal server error. Please try again later"
        safe_error_trace = error_trace if isinstance(e, FileNotFound) else generic_error
        error_dict = {
            "data": {},
            "messages": {
                "source": safe_error_trace
            }
        }
        task_status = CatvTaskStatusType.FAILED
        ConsumerErrorLogs.objects.create(
            topic=message.topic,
            message=request_body,
            error_trace=str(e)
        )
    finally:
        message = results or error_dict
        CatvRequestStatus.objects.filter(uid=message_id, user_id=user_id).update(status=task_status, result=message)
