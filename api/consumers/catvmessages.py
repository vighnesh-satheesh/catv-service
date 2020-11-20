import json
from operator import gt, lt
from uuid import UUID, uuid4

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.timezone import now

from api.catvutils.metrics import CatvMetrics
from api.exceptions import FileNotFound
from api.models import (
    AttachedFile,
    CatvTokens, CatvSearchType,
    CatvRequestStatus, CatvTaskStatusType,
    ConsumerErrorLogs, CatvResult,
    CatvJobQueue
)
from api.serializers import (
    CATVSerializer, CATVBTCCoinpathSerializer,
    CatvBtcPathSerializer, CATVEthPathSerializer
)
from api.settings import api_settings
from api.tasks import CatvHistoryTask, CatvPathHistoryTask

__all__ = ('process_catv_messages',)


def process_catv_messages(job: CatvJobQueue):
    message = job.message
    request_body = message
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
        },
        CatvTokens.TRON.value: {
            CatvSearchType.FLOW.value: CATVSerializer,
            CatvSearchType.PATH.value: CATVEthPathSerializer
        },
        CatvTokens.LTC.value: {
            CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
            CatvSearchType.PATH.value: CatvBtcPathSerializer
        },
        CatvTokens.BCH.value: {
            CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
            CatvSearchType.PATH.value: CatvBtcPathSerializer
        },
        CatvTokens.XRP.value: {
            CatvSearchType.FLOW.value: CATVSerializer,
            CatvSearchType.PATH.value: CATVEthPathSerializer
        },
        CatvTokens.EOS.value: {
            CatvSearchType.FLOW.value: CATVSerializer,
            CatvSearchType.PATH.value: CATVEthPathSerializer
        },
        CatvTokens.XLM.value: {
            CatvSearchType.FLOW.value: CATVSerializer,
            CatvSearchType.PATH.value: CATVEthPathSerializer
        },
        CatvTokens.BNB.value: {
            CatvSearchType.FLOW.value: CATVSerializer,
            CatvSearchType.PATH.value: CATVEthPathSerializer
        },
        CatvTokens.ADA.value: {
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
        source_depth = search_params.get("source_depth", 0)
        distribution_depth = search_params.get("distribution_depth", 0)
        search_params.update({'force_lookup': True})
        history_runner = CatvHistoryTask if search_type == CatvSearchType.FLOW.value else CatvPathHistoryTask
        print(search_params)
        
        serializer_obj = serializer_map[token_type][search_type](data=search_params)
        serializer_obj._token_type = token_type
        serializer_obj.is_valid(raise_exception=True)
        if search_type == CatvSearchType.FLOW.value:
            balanced_tx_limit = api_settings.CATV_TX_LIMIT
            balanced_addr_limit = api_settings.CATV_ADDRESS_LIMT
            if source_depth > 0 and distribution_depth > 0:
                balanced_tx_limit = balanced_tx_limit / 2
                balanced_addr_limit = balanced_addr_limit / 2
            core_results = serializer_obj.get_tracking_results(tx_limit=balanced_tx_limit, limit=balanced_addr_limit, save_to_db=False)
        else:
            core_results = serializer_obj.get_tracking_results(save_to_db=False)
        graph_data = core_results.get("graph", {})
        catv_metrics = CatvMetrics(graph_data)
        dist_analysis = {}
        src_analysis = {}
        if search_type == CatvSearchType.FLOW.value:
            if search_params.get("distribution_depth", 0) > 0:
                dist_analysis = catv_metrics.generate_metrics(gt)
            if search_params.get("source_depth", 0) > 0:
                src_analysis = catv_metrics.generate_metrics(lt)
        else:
            if search_params.get("depth", 0) > 0:
                dist_analysis = catv_metrics.generate_metrics(gt)
        catv_metrics.save_annotations()
        if 'graph_node_list' in graph_data and graph_data['graph_node_list']:
            if len(graph_data['node_list']) != len(graph_data['graph_node_list']):
                core_results["messages"]["source"] += f"\nThis address has too many transactions. Viewing all transactions would be difficult, "\
                    f"so we have generated the most relevant graph for you with some scaling down on each level to show nodes which have transacted the most."
            graph_data["node_list"] = graph_data["graph_node_list"]
            graph_data["edge_list"] = graph_data["graph_edge_list"] if graph_data["graph_edge_list"] else graph_data["edge_list"]
            print(len(graph_data["node_list"]))
            del graph_data["graph_node_list"]
            del graph_data["graph_edge_list"]
        results = {
            "data": {
                **graph_data,
                "dist_analysis": dist_analysis,
                "src_analysis": src_analysis
            },
            "messages": {**core_results["messages"]}
        }
        
        search_params.update({'user_id': user_id, 'token_type': token_type})
        if graph_data.get("node_list", {}):
            history_runner().run(history=search_params, from_history=False)
            task_status = CatvTaskStatusType.RELEASED
        else:
            history_runner().run(history=search_params, from_history=True)
            task_status = CatvTaskStatusType.FAILED
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
            topic="catv-requests",
            message=request_body,
            error_trace=error_trace
        )
    finally:
        message = results or error_dict
        with transaction.atomic():
            file = ContentFile(bytes(json.dumps(message).encode('UTF-8')), name=f"{uuid4()}.json")
            file_instance = AttachedFile.objects.create(file=file)
            request_instance = CatvRequestStatus.objects.get(uid=message_id, user_id=user_id)
            request_instance.status = task_status
            request_instance.updated = now()
            request_instance.save()
            CatvResult.objects.filter(request=request_instance).update(result_file=file_instance)
            job.delete()
