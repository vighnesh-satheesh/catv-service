import ast
import json
import traceback
import uuid

import pandas as pd
from django.core.exceptions import SuspiciousOperation
from django.db import transaction
from django.db.models import OuterRef, Subquery, Q, Case, When, Value, TextField
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _
from django_filters import rest_framework as filters
from rest_framework import generics, status
from rest_framework.authentication import get_authorization_header
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from api.permissions import IsCATVAuthenticated
from api.rpc.RPCClient import RPCClientUpdateUsageCatvCall, RPCClientFetchResultFileUid, RPCClientFetchResultFileList, \
    RPCClientCATVCheckTerraAccess, RPCClientUpdateUsageCSVCatvCall
from . import exceptions
from . import utils
from .catvutils.process_node_list import ProcessNodeList
from .exceptions import ValidationError
from .models import (
    CatvHistory, CatvTokens, CatvSearchType,
    CatvRequestStatus, CatvTaskStatusType, CatvResult,
    ProductType, CatvNodeLabelModel, CatvCSVJobQueue, ConsumerErrorLogs, CatvNeoCSVJobQueue
)
from .multitoken.tokens_auth import CachedTokenAuthentication, MultiToken
from .pagination import CatvRequestPagination, CustomPagination
from .response import APIResponse
from .serializers import (
    CATVBTCSerializer, CATVBTCTxlistSerializer,
    CATVHistorySerializer, CATVRequestListSerializer, CATVNodeLabelPostSerializer, TracerRecommendationsSerializer
)
from .settings import api_settings
from .tasks import (
    catv_history_task, CatvRequestTask
)
from .throttling import (
    CatvPostThrottle, CatvUsageExceededThrottle, CatvNoThrottle
)
from .utils import serializer_map, pattern_matches_token


class HealthCheckView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)

    def get(self, request):
        return APIResponse({
            "status": "ok",
        })


class MatchReportLabelsView(APIView):
    """
    Accepts a CSV of wallet_address,label and a report UID, matches wallets to nodes,
    and returns updated node_list plus total_amount per matched wallet.
    """

    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)

    def _load_report_and_retrieve_data(self, uid):
        """
        Load report data from GCS using the provided UID.
        
        Returns:
            dict: Parsed JSON results from the report file
            
        Raises:
            exceptions.CATVReportNotFound: If report not found
            exceptions.ValidationError: If results not generated yet
            exceptions.ServerError: If loading fails
        """
        try:
            catv_result = CatvResult.objects.select_related("request").get(
                request__uid__iexact=uid
            )
        except CatvResult.DoesNotExist:
            raise exceptions.CATVReportNotFound()

        if not catv_result.result_file_id:
            raise exceptions.ValidationError(
                "Results not generated yet. Please try again later."
            )

        file_id = str(catv_result.result_file_id)
        res = (RPCClientFetchResultFileUid().call(file_id)).decode("UTF-8")
        filename = api_settings.ATTACHED_FILE_S3_KEY_PREFIX + res

        try:
            body = utils.get_gcs_file(
                api_settings.ATTACHED_FILE_S3_BUCKET_NAME, filename
            )
        except SuspiciousOperation:
            raise exceptions.ValidationError(
                "Results not generated yet. Please try again later."
            )

        # Parse JSON once (optimization: removed double parsing)
        try:
            results = json.loads(body)
        except json.JSONDecodeError:
            # Fallback: try literal_eval if it's a string representation
            results = ast.literal_eval(body) if isinstance(body, str) else body

        if results == "False":
            raise exceptions.ValidationError(
                "Results not generated yet. Please try again later."
            )

        return results

    def post(self, request):
        uid = request.data.get("uid") or request.POST.get("uid")
        csv_file = request.FILES.get("file")

        if not uid:
            return APIResponse(
                {"data": {"error": "uid is required"}},
                status=400,
            )

        try:
            utils.validate_labels_csv_file(csv_file)
        except ValueError as e:
            return APIResponse(
                {"data": {"error": str(e)}},
                status=400,
            )

        # Load report from GCS
        try:
            results = self._load_report_and_retrieve_data(uid)
        except exceptions.APIException:
            raise
        except Exception:
            traceback.print_exc()
            raise exceptions.ServerError(
                detail="Failed to load report data for label matching."
            )

        data = results.get("data", {})
        node_list = data.get("node_list", [])
        item_list = data.get("item_list", [])

        # Read CSV content once and delegate matching/calculation to utils
        try:
            decoded = csv_file.read().decode("utf-8")
            match_result = utils.match_report_labels_from_csv(
                csv_content=decoded,
                node_list=node_list,
                item_list=item_list,
            )
        except ValueError as e:
            # Check if it's a chain type determination error
            error_msg = str(e)
            if "Cannot determine chain type" in error_msg:
                return APIResponse(
                    {
                        "data": {
                            "error": "Label matching could not be completed because the chain type could not be determined from the report data."
                        }
                    },
                    status=400,
                )
            # Other ValueError cases (e.g., CSV validation)
            return APIResponse(
                {"data": {"error": error_msg}},
                status=400,
            )
        except Exception:
            traceback.print_exc()
            raise exceptions.ServerError(
                detail="Failed to process CSV for label matching."
            )

        return APIResponse(
            {
                "data": match_result
            }
        )


def validate_request_parameters(token_type, search_type):
    allowed_tokens = [token.value for token in CatvTokens]
    allowed_search = [search.value for search in CatvSearchType]
    if token_type not in allowed_tokens:
        raise exceptions.ValidationError(f"Invalid token type. Supported: {(', ').join(allowed_tokens)}")
    if search_type not in allowed_search:
        raise exceptions.ValidationError(f"Invalid search type. Supported: {(', ').join(allowed_search)}")


def check_permission_for_lunc(token_type, user_details):
    if token_type == CatvTokens.LUNC.value:
        rpc_for_permission_check = RPCClientCATVCheckTerraAccess()
        res = (rpc_for_permission_check.call(user_details['user_id'])).decode('UTF-8')
        if "False" in res:
            print("User doesn't have permission to submit/view Terra reports.")
            return False
    return True


def submit_catv_request(token_type, search_type, history, request, is_legacy, is_bounty_track, is_api=False):
    catv_req_task = CatvRequestTask(api_settings.KAFKA_CATV_TOPIC,
                                    token_type=token_type,
                                    search_type=search_type,
                                    search_params=history,
                                    user=request.user,
                                    is_legacy=is_legacy,
                                    is_bounty_track=is_bounty_track
                                    )
    catv_req_task.run()
    task = catv_req_task.save()
    task_serializer = CATVRequestListSerializer(task)

    if not is_api:
        rpc = RPCClientUpdateUsageCatvCall()
        auth = get_authorization_header(request).split()
        token = auth[1].decode()
        timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)
        user_details, verified_token = MultiToken.get_user_from_key(request)
        if is_bounty_track:
            credits_required = user_details['usage']['credits_requirement']['track']
        else:
            credits_required = user_details['usage']['credits_requirement']['catv']
        user_rpc = {"id": user_details['user_id'], "token": str(token), "timestamp": str(timestamp),
                    'source': 'portal',
                    'is_bounty_track': is_bounty_track,
                    "uid": str(user_details['user_uid']),
                    "credits_required": credits_required}
        res = (rpc.call(user_rpc)).decode('UTF-8')
        print("Submission Status: ", res)

    return task_serializer.data


# Original view refactored to use new functions
class CATVView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)

    def get_throttles(self):
        if self.request.method.lower() == 'post':
            return [CatvUsageExceededThrottle(), CatvPostThrottle(), ]
        return None

    def post(self, request):
        token_type = request.query_params.get('token_type', CatvTokens.ETH.value)
        search_type = request.query_params.get('search_type', CatvSearchType.FLOW.value)
        is_legacy_param = request.query_params.get('is_legacy', 'True')
        if isinstance(is_legacy_param, str):
            is_legacy = is_legacy_param.lower() != 'false'
        else:
            is_legacy = bool(is_legacy_param)

        is_bounty_track = request.query_params.get('is_bounty_track', 'False')
        if isinstance(is_bounty_track, str):
            is_bounty_track = is_bounty_track.lower() != 'false'
        else:
            is_bounty_track = bool(is_bounty_track)
        print(f"is_bounty_track: {is_bounty_track}")
        # Validate request parameters
        validate_request_parameters(token_type, search_type)

        serializer_cls = serializer_map[token_type][search_type]
        serializer = serializer_cls(data=request.data, context={"request": request})
        serializer._token_type = token_type
        serializer.is_valid(raise_exception=True)
        history = serializer.data
        user_details, verified_token = MultiToken.get_user_from_key(request)

        # Check permission for LUNC
        if not check_permission_for_lunc(token_type, user_details):
            return APIResponse({
                "data": {},
                "messages": {
                    "source": "No access for this request. Please contact support for more information."
                }
            })

        try:
            # Submit CATV request
            task_data = submit_catv_request(token_type, search_type, history, request, is_legacy, is_bounty_track, is_api=False)
            return APIResponse({
                "data": task_data,
                "messages": {
                    "source": "Address successfully submitted for report generation."
                }
            })
        except Exception:
            traceback.print_exc()
            raise exceptions.ServerError(
                detail="Something went wrong while submitting your request. Please try again later.")


# Add this to api/views.py

class TracerRecommendationsView(APIView):
    """
    GET endpoint to retrieve trace recommendations based on transaction count.

    This API is called after initial input validation to provide recommendations
    for depth and date range settings before generating a full CATV report.

    Query Parameters:
        - blockchain (required): Blockchain identifier (ETH, BSC, BTC, etc.)
        - wallet_address (optional): Wallet address to analyze
        - transaction_hash (optional): Transaction hash to analyze
        - token_contract_address (optional): Token contract address for EVM/TRON chains
        - sender_wallet_address (optional): Required for UTXO chains with transaction_hash
        - receiver_wallet_address (optional): Required for UTXO chains with transaction_hash

    Returns:
        JSON response with:
        - transaction_count: Number of transactions found
        - depth_count: Recommended depth value (1, 3, or 5)
        - depth_indicator: Human-readable depth (shallow, medium, deep)
        - date_range: Recommended date range (Last 30d, Last 90d, etc.)
        - alert (optional): Heavy wallet warning if tx_count > 10,000
        - address (optional): Validated address from transaction hash
    """
    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        """Handle GET request for recommendations."""
        # Extract query parameters
        data = {
            'blockchain': request.query_params.get('blockchain'),
            'wallet_address': request.query_params.get('wallet_address'),
            'transaction_hash': request.query_params.get('transaction_hash'),
            'token_contract_address': request.query_params.get('token_contract_address'),
            'sender_wallet_address': request.query_params.get('sender_wallet_address'),
            'receiver_wallet_address': request.query_params.get('receiver_wallet_address'),
        }

        # Remove None values
        data = {k: v for k, v in data.items() if v is not None}

        # Validate and get recommendations
        serializer = TracerRecommendationsSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        try:
            recommendations = serializer.get_recommendations()

            return APIResponse({
                'data': recommendations,
                'messages': {
                    'info': 'Recommendations generated successfully.'
                }
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise exceptions.ServerError(
                detail="Failed to generate recommendations. Please try again later."
            )


#obsolete
# class CATVBTCView(APIView):
#     authentication_classes = (CachedTokenAuthentication, )
#     permission_classes = (IsCATVAuthenticated, )
#
#     def get_throttles(self):
#         if self.request.method.lower() == 'post':
#             return [CatvUsageExceededThrottle(), CatvPostThrottle(), ]
#
#     def post(self, request):
#         serializer = CATVBTCSerializer(
#             data=request.data, context={"request": request})
#         serializer.is_valid(raise_exception=True)
#         history = serializer.data
#         if api_settings.SWITCH_CATV_KAFKA:
#             try:
#                 catv_req_task = CatvRequestTask(api_settings.KAFKA_CATV_TOPIC,
#                                                 token_type=CatvTokens.BTC.value,
#                                                 search_type=CatvSearchType.FLOW.value,
#                                                 search_params=history,
#                                                 user=request.user
#                                                 )
#                 catv_req_task.run()
#                 catv_req_task.save()
#
#                 rpc = RPCClientUpdateUsageCatvCall()
#                 auth = get_authorization_header(request).split()
#                 token = auth[1].decode()
#                 timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)
#                 user_details, verified_token = MultiToken.get_user_from_key(request)
#                 user_rpc = {"id": user_details['user_id'], "token": str(token), "timestamp": str(timestamp), 'source': 'portal',
#                             "uid": str(user_details['user_uid']), "credits_required": user_details['usage']['credits_requirement']['catv']}
#                 res = (rpc.call(user_rpc)).decode('UTF-8')
#                 print("Submission Status: ", res)
#
#                 return APIResponse({
#                     "data": {},
#                     "messages": {
#                         "source": "Address successfully submitted for report generation."
#                     }
#                 })
#             except:
#                 raise exceptions.ServerError(detail=f"Something went wrong while submitting your request."
#                                              f"Please try again later.")
#         else:
#             user_details, verified_token = MultiToken.get_user_from_key(request)
#             history.update({'user_id': user_details["user_id"], 'token_type': CatvTokens.BTC.value})
#             results = serializer.get_tracking_results()
#             catv_history_task.delay(history=history, from_history=False)
#             if "graph" in results and "messages" in results:
#                 return APIResponse({
#                     "data": {**results["graph"]},
#                     "messages": {**results["messages"]}
#                 })
#             return APIResponse({
#                 "data": results
#             })


class CATVBTCTxlistView(APIView):
    authentication_classes = (CachedTokenAuthentication, )
    permission_classes = (IsCATVAuthenticated, )

    def get_throttles(self):
        if self.request.method.lower() == 'post':
            return [CatvUsageExceededThrottle(), CatvPostThrottle(), ]

    def post(self, request):
        serializer = CATVBTCTxlistSerializer(
            data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        txlist = serializer.get_btc_txlist()
        if not txlist:
            raise exceptions.FileNotFound(
                "No transactions could be found for this address. Please try again later.")
        return APIResponse({
            "data": txlist
        })


class CATVHistoryView(APIView):
    authentication_classes = (CachedTokenAuthentication, )
    permission_classes = (IsCATVAuthenticated, )

    def get(self, request):
        serializer = CATVHistorySerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        data = serializer.data
        print("Serializer Data:", data)

        user_details, verified_token = MultiToken.get_user_from_key(request)
        history_with_tokens = self.get_history_list(user_details["user_id"], request.GET['token_type'].upper())
        history_list = []
        for item in history_with_tokens:
            obj = {
                "wallet_address": item[0],
                "token_address": item[1],
                "source_depth": item[2],
                "distribution_depth": item[3],
                "transaction_limit": item[4],
                "from_date": item[5],
                "to_date": item[6],
                "token_type": item[7]
            }
            history_list.append(obj)

        return APIResponse({
            "data": history_list
        })

    def get_history_list(self, user_id, token_type):
        filter_queries = Q(user_id=user_id)
        if token_type:
            filter_queries &= Q(token_type=token_type)
        objs = CatvHistory.objects.filter(filter_queries).values_list('wallet_address', 'token_address', 'source_depth',
                                                                      'distribution_depth', 'transaction_limit',
                                                                      'from_date', 'to_date', 'token_type').order_by(
            '-pk')[:10]
        return list(objs)


class CATVRequestsView(generics.ListAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)
    pagination_class = CatvRequestPagination
    filter_backends = (filters.DjangoFilterBackend,)
    
    def list(self, request, *args, **kwargs):
        status = self.request.query_params.get("status", None)
        is_bt_request = request.query_params.get('is_bt_request', 'False')
        if isinstance(is_bt_request, str):
            is_bt_request = is_bt_request.lower() != 'false'
        else:
            is_bt_request = bool(is_bt_request)
        print(f"{is_bt_request=}")
        if status and status not in \
            [CatvTaskStatusType.PROGRESS.value,
             CatvTaskStatusType.RELEASED.value,
             CatvTaskStatusType.FAILED.value]:
            raise exceptions.ValidationError("Invalid status type parameter")
        page = self.request.GET.get("page", 1)
        page = int(page)
        queryset = self.filter_queryset(self.get_queryset(request.user["user_id"], status, is_bt_request))
        page = self.paginate_queryset(queryset)
        serializer = CATVRequestListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def get_queryset(self, user_id, status, is_bt_request=False):
        filter_queries = Q(user_id=user_id)
        if status:
            filter_queries &= Q(status=status)
        filter_queries &= Q(is_bounty_track=is_bt_request)
        # fitler requests based on the source (BountyTrack/CATV)

        # Subquery to get the user_error_message from ConsumerErrorLogs
        error_message_subquery = ConsumerErrorLogs.objects.filter(
            request=OuterRef('pk')
        ).order_by('-logged_time').values('user_error_message')[:1]

        queryset = CatvRequestStatus.objects.filter(filter_queries).annotate(
            error_message=Coalesce(
                Case(
                    When(status=CatvTaskStatusType.FAILED, then=Subquery(error_message_subquery)),
                    default=Value(''),
                    output_field=TextField(),
                ),
                Value('Something went wrong! Please try again.'),
                output_field=TextField(),
            )
        ).order_by('-pk')

        return queryset

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data, data_key="items")


class CATVReportView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)

    def get_throttles(self):
        if self.request.method.lower() in ['put', 'post']:
            return [CatvUsageExceededThrottle(), CatvPostThrottle(), ]
        return [CatvNoThrottle(), ]
    
    def get_object(self, pk):
        try:
            return CatvResult.objects.select_related('request').get(request__uid__iexact=pk)
        except CatvRequestStatus.DoesNotExist:
            raise exceptions.CATVReportNotFound()
        except CatvResult.DoesNotExist:
            raise exceptions.CATVReportNotFound()
    
    def get_related_object(self, pk):
        try:
            return CatvRequestStatus.objects.get(uid__iexact=pk)
        except CatvRequestStatus.DoesNotExist:
            raise exceptions.CATVReportNotFound()

    def _apply_user_labels_to_nodes(self, results, request_uid):
        """Helper method to efficiently apply user labels to nodes"""
        if not results.get("data", {}).get("node_list"):
            return results

        # Get all labels for this report in a single query
        node_labels = CatvNodeLabelModel.objects.filter(
            uid=request_uid
        ).values('wallet_address', 'label')

        # Create a mapping of wallet addresses to labels for O(1) lookup
        label_mapping = {
            label['wallet_address']: label['label']
            for label in node_labels
        }

        # Update nodes in a single pass
        for node in results["data"]["node_list"]:
            if node['address'] in label_mapping:
                node['userLabel'] = label_mapping[node['address']]
                node['group'] = 'User Label'

        return results

    def get(self, request, pk=None):
        obj = self.get_object(pk)
        file_id = str(obj.result_file_id)

        res = (RPCClientFetchResultFileUid().call(file_id)).decode("UTF-8")
        print("RES", res)
        filename = api_settings.ATTACHED_FILE_S3_KEY_PREFIX + res

        try:
            body = utils.get_gcs_file(api_settings.ATTACHED_FILE_S3_BUCKET_NAME,filename)#s3_obj.get()['Body'].read()
        except SuspiciousOperation:
            return APIResponse({
                "data": {},
                "messages": {
                    "source": "Results not generated yet. Please try again later."
                }
            })

        results = json.loads(body)
        if isinstance(results, str):
            results = ast.literal_eval(results)

        if results == "False":
            return APIResponse({
                "data": {},
                "messages": {
                    "source": "Results not generated yet. Please try again later."
                }
            })

        if "messages" in results.keys():
            for k, v in results["messages"].items():
                results["messages"][k] = _(v)

        serializer = CATVRequestListSerializer(obj.request)
        request_params = serializer.data
        results = self._apply_user_labels_to_nodes(results, request_params["uid"])

        node_list = results['data']['node_list']
        if type(request_params['depth']) is int:
            request_params['depth'] = f"{request_params['depth']} / {request_params['depth']}"
        process_node_list_obj = ProcessNodeList(node_list, request_params['depth'])
        process_node_list_obj.create_node_list_by_depth()
        results["data"]["src_node_list_by_depth"] = process_node_list_obj.get_src_node_lists()
        results["data"]["dist_node_list_by_depth"] = process_node_list_obj.get_dist_node_lists()

        return APIResponse({
            **results,
            "request_params": serializer.data
        })
    
    def put(self, request, pk=None):
        obj = self.get_related_object(pk)
        reverse_token_map = {
            "Ethereum/ERC20": CatvTokens.ETH.value,
            "Bitcoin": CatvTokens.BTC.value,
            "Tron": CatvTokens.TRON.value,
            "Litecoin": CatvTokens.LTC.value,
            "Ripple": CatvTokens.XRP.value,
            "EOS": CatvTokens.EOS.value,
            "Stellar": CatvTokens.XLM.value,
            "Binance Coin": CatvTokens.BNB.value,
            "Cardano": CatvTokens.ADA.value,
            "Binance Smart Chain": CatvTokens.BSC.value,
            "KAIA": CatvTokens.KLAY.value,
            "Bitcoin Cash": CatvTokens.BCH.value,
            "LUNC": CatvTokens.LUNC.value,
            "Doge Coin": CatvTokens.DOGE.value,
            "Zcash": CatvTokens.ZEC.value,
            "DASH": CatvTokens.DASH.value,
            "Avalanche": CatvTokens.AVAX.value,
            "Fantom": CatvTokens.FTM.value,
            "Polygon": CatvTokens.POL.value,
            "Solana": CatvTokens.SOL.value,
            "Arbitrum": CatvTokens.ARB.value,
            "Arbitrum Nova": CatvTokens.ARBNOVA.value,
            "Optimism": CatvTokens.OP.value,
            "Base": CatvTokens.BASE.value,
            "Linea": CatvTokens.LINEA.value,
            "Blast": CatvTokens.BLAST.value,
            "Scroll": CatvTokens.SCROLL.value,
            "Mantle": CatvTokens.MANTLE.value,
            "opBNB": CatvTokens.OPBNB.value,
            "BitTorrent": CatvTokens.BTT.value,
            "Celo": CatvTokens.CELO.value,
            "Fraxtal": CatvTokens.FRAXTAL.value,
            "Gnosis": CatvTokens.GNOSIS.value,
            "Memecore": CatvTokens.MEMECORE.value,
            "Moonbeam": CatvTokens.MOONBEAM.value,
            "Moonriver": CatvTokens.MOONRIVER.value,
            "Taiko": CatvTokens.TAIKO.value,
            "XDC": CatvTokens.XDC.value,
            "Apechain": CatvTokens.APECHAIN.value,
            "World": CatvTokens.WORLD.value,
            "Sonic": CatvTokens.SONIC.value,
            "Unichain": CatvTokens.UNICHAIN.value,
            "Abstract": CatvTokens.ABSTRACT.value,
            "Berachain": CatvTokens.BERACHAIN.value,
            "Swellchain": CatvTokens.SWELLCHAIN.value,
            "Monad": CatvTokens.MONAD.value,
            "HyperEVM": CatvTokens.HYPEREVM.value,
            "Katana": CatvTokens.KATANA.value,
            "Sei": CatvTokens.SEI.value,
            "Stable": CatvTokens.STABLE.value,
            "Plasma": CatvTokens.PLASMA.value
        }
        is_legacy_param = request.query_params.get('is_legacy', 'True')
        if isinstance(is_legacy_param, str):
            is_legacy = is_legacy_param.lower() != 'false'
        else:
            is_legacy = bool(is_legacy_param)
        is_bounty_track = request.query_params.get('is_bounty_track', 'False')
        if isinstance(is_bounty_track, str):
            is_bounty_track = is_bounty_track.lower() != 'false'
        else:
            is_bounty_track = bool(is_bounty_track)
        token_type = utils.determine_wallet_type(obj.token_type)
        has_from_address = obj.params.get("address_from", "")
        token_type = reverse_token_map[token_type]
        auth = get_authorization_header(request).split()
        token = auth[1].decode()
        timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP', None)
        user_details, verified_token = MultiToken.get_user_from_key(request)
        if token_type == CatvTokens.LUNC.value:
            rpc_for_permission_check = RPCClientCATVCheckTerraAccess()
            res = (rpc_for_permission_check.call(user_details['user_id'])).decode('UTF-8')
            if "False" in res:
                print("User doesn't have permission to submit/view Terra reports.")
                return APIResponse({
                    "data": {},
                    "messages": {
                        "source": "No access for this request. Please contact support for more information."
                    }
                })

        search_type = CatvSearchType.PATH.value if has_from_address else CatvSearchType.FLOW.value
        catv_req_task = CatvRequestTask(api_settings.KAFKA_CATV_TOPIC,
                                        token_type=token_type,
                                        search_type=search_type,
                                        search_params=obj.params,
                                        user=request.user,
                                        is_legacy=is_legacy,
                                        is_bounty_track=is_bounty_track
                                        )
        catv_req_task.run()
        task = catv_req_task.save()
        task_serializer = CATVRequestListSerializer(task)

        rpc = RPCClientUpdateUsageCatvCall()
        auth = get_authorization_header(request).split()
        if is_bounty_track:
            credits_required = user_details['usage']['credits_requirement']['track']
        else:
            credits_required = user_details['usage']['credits_requirement']['catv']
        user_rpc = {"id": user_details['user_id'], "token": str(token), "timestamp": str(timestamp), 'source': 'portal',
                    "uid": str(user_details['user_uid']), "credits_required": credits_required}
        res = (rpc.call(user_rpc)).decode('UTF-8')
        print("Submission Status: ", res)

        return APIResponse({
            "data": {
                **task_serializer.data
            },
            "messages": {
                "source": "Address successfully re-submitted for report generation."
            }
        })


class CatvRequestStatusView(APIView):
    authentication_classes = ()
    permission_classes = ()

    def get(self, request, request_uid=None):
        try:
            catv_request = CatvRequestStatus.objects.get(uid=request_uid)
        except CatvRequestStatus.DoesNotExist:
            return APIResponse({'detail': 'Not Found.'}, status=status.HTTP_404_NOT_FOUND)

        request_status = catv_request.status == CatvTaskStatusType.RELEASED
        error_status = catv_request.status == CatvTaskStatusType.FAILED
        message = ""
        if request_status:
            message = "Report ready."
        elif error_status:
            message = "Failed to generate report."
        return APIResponse({'report_ready': request_status, 'error_status': error_status, 'message': message})


class CATVMultiReportView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)

    def get_objects(self, pks):
        try:
            # return CatvResult.objects.select_related('request').get(request__uid__iexact=pk)
            return CatvResult.objects.select_related('request').filter(request__uid__in=pks).order_by('result_file_id')
        except CatvRequestStatus.DoesNotExist:
            raise exceptions.CATVReportNotFound()
        except CatvResult.DoesNotExist:
            raise exceptions.CATVReportNotFound()

    def get(self, request, pk=None):
        ids = self.request.query_params.get('ids', None)
        final_result = []
        is_dist_value = []
        is_source_value = []
        result_file_ids = []
        if ids is not None:
            main_ids = [x.strip() for x in ids.split(',')]
            catv_results = self.get_objects(main_ids)
            for obj in catv_results:
                if not obj.result_file_id:
                    return APIResponse({
                        "data": {},
                        "messages": {
                            "source": "Results not generated yet. Please try again later."
                        }
                    })
                result_file_ids.append(obj.result_file_id)

            rpc = RPCClientFetchResultFileList()
            res = (rpc.call(result_file_ids)).decode('UTF-8')
            result_files = ast.literal_eval(res)
            print("result_files:- ", result_files)
            if len(result_files) > 0:
                for catv_result, result_file in zip(catv_results, result_files):

                    print('result_file[id]', result_file['id'])
                    print('catv_result[result_file_id]', catv_result.result_file_id)
                    filename = api_settings.ATTACHED_FILE_S3_KEY_PREFIX + result_file['uid']
                    try:
                        body = utils.get_gcs_file(api_settings.ATTACHED_FILE_S3_BUCKET_NAME,filename)
                    except SuspiciousOperation:
                        return APIResponse({
                        "data": {},
                        "messages": {
                            "source": "Results not generated yet. Please try again later."
                        }
                    })
                    results = json.loads(body)
                    if isinstance(results, str):
                        results = ast.literal_eval(results)

                    if "messages" in results.keys():
                        for k, v in results["messages"].items():
                            results["messages"][k] = _(v)
                    serializer = CATVRequestListSerializer(catv_result.request)
                    depth_arr = serializer.data["depth"].split('/')
                    is_dist_value.append(int(depth_arr[1]))
                    is_source_value.append(int(depth_arr[0]))
                    for i in range(len(results["data"]["item_list"])):
                        results["data"]["item_list"][i].update({'id': serializer.data['id']})
                    final_result.extend(results["data"]["item_list"])
        results["data"]["item_list"] = final_result
        return APIResponse({
            **results,
            "isDistValue": is_dist_value,
            "isSourceValue": is_source_value,
            "request_params": serializer.data
        })


class CATVRequestDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)

    def get_object(self, request, pk):
        try:
            user_details, verified_token = MultiToken.get_user_from_key(self.request)
            obj = CatvRequestStatus.objects.get(uid=pk)
            if obj.user_id != user_details['user_id']:
                raise exceptions.NotAllowedError(detail="You are only allowed to access your requests")
            return obj
        except CatvRequestStatus.DoesNotExist:
            raise exceptions.FileNotFound(detail="No matching request exists")

    def get(self, request, pk=None):
        obj = self.get_object(request, pk)
        serializer = CATVRequestListSerializer(obj, context={'request': request})
        data = serializer.data
        return APIResponse({
            'data': {
                'request': data
            }
        })

    def patch(self, request, pk=None):
        obj = self.get_object(request, pk)
        new_labels = request.data.get('labels', [])
        obj.labels = new_labels
        obj.save()
        serializer = CATVRequestListSerializer(obj, context={'request': request})
        data = serializer.data
        return APIResponse({
            'data': {
                'request': data
            }
        })

class RequestSearchView(generics.ListAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)
    pagination_class = CustomPagination
    filter_backends = (filters.DjangoFilterBackend,)

    def list(self, request, *args, **kwargs):
        valid_search_types = [ProductType.CATV.value]
        search_type = self.request.query_params.get("type", "catv")
        query = self.request.query_params.get("q", None)
        status = self.request.query_params.get("status", None)
        order_by = self.request.GET.get('order_by', 'id_desc')
        order_by = order_by.split('_')
        order_key = '-id'
        if order_by[1] == 'asc':
            order_key = 'id'
        if search_type not in valid_search_types:
            raise exceptions.ValidationError(
                f"Invalid search type parameter. Valid values: {', '.join(valid_search_types)}")
        if not query:
            raise exceptions.ValidationError("q is required.")
        if len(query) > 1024:
            raise exceptions.ValidationError("q is too long.")
        if status and status not in \
            [CatvTaskStatusType.PROGRESS.value,
             CatvTaskStatusType.RELEASED.value,
             CatvTaskStatusType.FAILED.value]:
            raise exceptions.ValidationError("Invalid status type parameter")

        serializer_cls = CATVRequestListSerializer
        queryset = self.filter_queryset(self.get_queryset(search_type, query, status, order_key))

        page = self.paginate_queryset(queryset)
        serializer = serializer_cls(page, many=True)
        return self.get_paginated_response(serializer.data)

    def get_catv_queryset(self, query, status, order_key):
        filter_queries = Q(params__icontains=query)
        filter_queries |= Q(labels__arrayilike=query)
        if status:
            filter_queries &= Q(status=status)
        user_details, verified_token = MultiToken.get_user_from_key(self.request)
        filter_queries &= Q(user_id=user_details['user_id'])
        objs = CatvRequestStatus.objects.filter(filter_queries).distinct('id').order_by(order_key)
        return objs

    def get_queryset(self, search_type, query, status, order_key):
        objs = None
        if search_type == ProductType.CATV.value:
            return self.get_catv_queryset(query, status, order_key)
        return objs

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data, data_key="items")

class CATVNodeLabelView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)
    
    def post(self, request):
        user_details, verified_token = MultiToken.get_user_from_key(request)
        serializer = CATVNodeLabelPostSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(user_id=user_details['user_id'])
        return APIResponse({
            'data': serializer.data
        })
    
    def delete(self, request):
        user_details, verified_token = MultiToken.get_user_from_key(request)
        uid = self.request.query_params.get('uid')
        wallet_address = self.request.query_params.get('wallet_address')
        user_id = user_details['user_id']

        if not uid or not wallet_address:
            return APIResponse({
                "data": {
                    "error":  "Both uid and wallet_address are required"
                }
            })

        label = CatvNodeLabelModel.objects.filter(
            uid=uid,
            wallet_address=wallet_address
        ).first()

        if not label:
            return APIResponse({
                "data": {
                    "error": "No matching label found"
                }
            }, status=404)

        # Check if the current user is the creator of the label
        if label.user_id != user_id:
            return APIResponse({
                "data": {
                    "error": "You do not have the required permission to delete this label."
                }
            }, status=403)

        # If we get here, the user is authorized to delete the label
        label.delete()

        return APIResponse({
            "data": "Successfully Deleted"
        })


class CATVCSVUpload(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsCATVAuthenticated,)

    REQUIRED_COLUMNS = {
        'token_type', 'wallet_address', 'source_depth',
        'distribution_depth', 'from_date', 'to_date',
        'token_address', 'transaction_limit'
    }

    DTYPE_MAP = {
        'source_depth': 'Int64',
        'distribution_depth': 'Int64',
        'transaction_limit': 'Int64',
        'token_type': 'str',
        'wallet_address': 'str',
        'from_date': 'str',
        'to_date': 'str',
        'token_address': 'str'
    }

    def get_throttles(self):
        if self.request.method.lower() == 'post':
            return [CatvUsageExceededThrottle(), CatvPostThrottle()]
        return []

    def validate_csv(self, df: pd.DataFrame) -> bool:
        """Validate CSV structure and data types."""
        if set(df.columns) != self.REQUIRED_COLUMNS:
            raise ValidationError(_("CSV format is incorrect. Please check column names."))

        # Validate integer columns
        integer_columns = ['source_depth', 'distribution_depth', 'transaction_limit']
        for col in integer_columns:
            if not pd.api.types.is_integer_dtype(df[col]):
                raise ValidationError(_(f"Column {col} must contain only integer values"))

        return True

    def process_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process and clean the dataframe."""
        # Chain operations for better performance
        df = (df
        .drop_duplicates(subset="wallet_address", keep="first")
        .assign(
            token_address=lambda x: x['token_address'].fillna("0x0000000000000000000000000000000000000000"),
            from_date=lambda x: pd.to_datetime(x['from_date']).dt.strftime('%Y-%m-%d'),
            to_date=lambda x: pd.to_datetime(x['to_date']).dt.strftime('%Y-%m-%d')
        ))

        # Filter valid wallet addresses using existing pattern_matches_token function
        valid_addresses = df.apply(
            lambda row: bool(pattern_matches_token(row['wallet_address'], row['token_type'])),
            axis=1
        )
        return df[valid_addresses]

    def check_terra_permission(self, df: pd.DataFrame, user_id: str) -> pd.DataFrame:
        """Check Terra permission and filter if necessary."""
        if (df['token_type'] == CatvTokens.LUNC.value).any():
            rpc_client = RPCClientCATVCheckTerraAccess()
            response = rpc_client.call(user_id).decode('UTF-8')

            if "False" in response:
                return df[df['token_type'] != CatvTokens.LUNC.value]
        return df

    def post(self, request):
        try:
            # Read and validate CSV
            csv_file = request.FILES['file']
            df = pd.read_csv(csv_file, dtype=self.DTYPE_MAP)
            is_legacy_param = request.query_params.get('is_legacy', 'True')
            if isinstance(is_legacy_param, str):
                is_legacy = is_legacy_param.lower() != 'false'
            else:
                is_legacy = bool(is_legacy_param)
            is_bounty_track = request.query_params.get('is_bounty_track', 'False')
            if isinstance(is_bounty_track, str):
                is_bounty_track = is_bounty_track.lower() != 'false'
            else:
                is_bounty_track = bool(is_bounty_track)
            print(f"{is_bounty_track=}")
            if df.empty:
                return APIResponse({
                    "data": {"error": "CSV file is empty"}
                })

            # Basic validation
            self.validate_csv(df)

            # Get user details and validate credits
            user_details, verified_token = MultiToken.get_user_from_key(request)

            # Process dataframe
            processed_df = self.process_dataframe(df)
            processed_df = self.check_terra_permission(processed_df, user_details['user_id'])

            final_length = len(processed_df)
            if final_length == 0:
                return APIResponse({
                    "data": {"error": "No valid entries found after processing"}
                })

            # Check credits
            credits_per_addr = user_details['usage']['credits_requirement']['catv']
            credits_required = final_length * credits_per_addr
            if user_details['usage']['credits_left'] < credits_required:
                return APIResponse({
                    "data": {
                        "error": "You do not have sufficient usage credits to process this CSV. Please purchase more credits to continue."}
                })

            # Prepare bulk create data
            job_queue = []
            request_status = []
            result_status = []
            csv_job_queue_class = CatvNeoCSVJobQueue
            if is_legacy:
                csv_job_queue_class = CatvCSVJobQueue

            # Convert DataFrame to records for processing
            records = processed_df.to_dict('records')

            for params in records:
                message_id = uuid.uuid4()

                # Prepare job queue entry
                job_queue.append(csv_job_queue_class(
                    message={
                        "message_id": message_id.hex,
                        "user_id": request.user["user_id"],
                        "token_type": params['token_type'],
                        "search_params": params
                    },
                    retries_remaining=1
                ))

                # Prepare request status entry
                status = CatvRequestStatus(
                    uid=message_id,
                    params=params,
                    user_id=request.user["user_id"],
                    token_type=params['token_type'],
                    is_legacy=is_legacy,
                    is_bounty_track=is_bounty_track
                )
                request_status.append(status)

                # Prepare result entry
                result_status.append(CatvResult(request=status))

            # Bulk create in transaction with chunks
            with transaction.atomic():
                for chunk in [job_queue[i:i + 50] for i in range(0, len(job_queue), 100)]:
                    csv_job_queue_class.objects.bulk_create(chunk)
                for chunk in [request_status[i:i + 50] for i in range(0, len(request_status), 100)]:
                    CatvRequestStatus.objects.bulk_create(chunk)
                for chunk in [result_status[i:i + 50] for i in range(0, len(result_status), 100)]:
                    CatvResult.objects.bulk_create(chunk)

            # Update usage credits
            rpc = RPCClientUpdateUsageCSVCatvCall()
            auth = get_authorization_header(request).split()
            token = auth[1].decode()
            timestamp = request.META.get('HTTP_X_AUTHORIZATION_TIMESTAMP')

            user_rpc = {
                "id": user_details['user_id'],
                "token": str(token),
                "timestamp": str(timestamp),
                "uid": str(user_details['user_uid']),
                "csv_records": final_length,
                "credits_required": credits_per_addr,
                "is_bounty_track": is_bounty_track
            }

            res = (rpc.call(user_rpc)).decode('UTF-8')
            print(f"Usage credits update status: {res}")

            return APIResponse({
                "data": records,
                "messages": {
                    "source": f"{final_length} Addresses are successfully submitted for report generation."
                }
            })

        except pd.errors.EmptyDataError:
            return APIResponse({
                "data": {"error": "Empty CSV file"}
            })
        except pd.errors.ParserError:
            return APIResponse({
                "data": {"error": "Invalid CSV format"}
            })
        except ValidationError as e:
            return APIResponse({
                "data": {"error": str(e)}
            })
        except Exception as e:
            traceback.print_exc()
            raise exceptions.ServerError(
                detail="Something went wrong while submitting your request. Please try again later."
            )
