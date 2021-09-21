import gzip
import datetime
import json
import math
from operator import gt, lt
import pytz
from random import randrange
import socket

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django_filters import rest_framework as filters
from django.db.models import F, Q, When, Value, Case as CaseFunc, IntegerField
from django.db import transaction, IntegrityError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db import connection, connections
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.decorators import api_view, permission_classes, authentication_classes

from social_django.utils import psa
from weasyprint import CSS
from weasyprint.fonts import FontConfiguration
from web3.auto.infura import w3
from web3 import Web3
from kafka import KafkaProducer
from requests.exceptions import HTTPError
import requests

from .models import (
    User, Case, Indicator, CaseIndicator, ICO, CaseStatus, Key, Comment, CaseHistory,
    Notification, NotificationType,
    AttachedFile, UserPermission, UppwardRewardInfo,
    UserStatus,
    IndicatorPatternType, IndicatorPatternSubtype, IndicatorEnvironment, IndicatorVector, IndicatorSecurityCategory,
    RewardSetting, ProductType, Organization, OrganizationInvites, OrganizationInviteStatus, OrganizationUser,
    CatvHistory, CatvTokens, CatvPathHistory, InviteType, OrganizationUserStatus,
    CatvSearchType, CatvRequestStatus, CatvTaskStatusType,
    UserIndicator, IndicatorPoint, CatvResult,
    Role, RoleUsageLimit, UserRoles,
    UserUpgrade, UpgradeVerifyStatus, CaraSearchHistory,
    SecurityTag, CustomerSecurityTag
)
from .serializers import (
    CATVSerializer, CATVBTCSerializer, CATVBTCTxlistSerializer,
     CATVHistorySerializer, CATVBTCCoinpathSerializer,
    CATVEthPathSerializer, CatvBtcPathSerializer,
    CATVRequestListSerializer
)
from .throttling import (
    SignUpThrottle, UserLoginThrottle, ChangePasswordThrottle,
    FileUploadThrottle, CasePostThrottle,
    EmailVerificationThrottle,
    IndicatorPostThrottle, CatvPostThrottle, CatvUsageExceededThrottle,
    CaraUsageExceededThrottle, CaraPostThrottle, GuestSearchThrottle,
    CatvNoThrottle, UpgradePlanThrottle, UpgradePlanNoThrottle)
from .response import APIResponse, FileResponse, FileRenderer
from .pagination import CustomPagination, CatvRequestPagination
from . import exceptions
from . import permissions
from . import utils
from .multitoken.tokens_auth import CachedTokenAuthentication, MultiToken
from .settings import api_settings
from .cache import DefaultCache
from .cache.catv import TrackingCache
from .constants import Constants
from .tasks import (
    CacheLeftPanelValuesTask, CatvHistoryTask, CacheNumberOfIndicatorsCases,
    CatvPathHistoryTask, CaseMessageTask, CatvRequestTask,
    UserRoleUpdateTask
)
from .catvutils.metrics import CatvMetrics


class HealthCheckView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)

    def get(self, request):
        return APIResponse({
            "status": "ok"
        })


class CATVView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_throttles(self):
        if self.request.method.lower() == 'post':
            return [CatvUsageExceededThrottle(), CatvPostThrottle(), ]

    def post(self, request):
        token_type = self.request.query_params.get('token_type', CatvTokens.ETH.value)
        search_type = self.request.query_params.get('search_type', CatvSearchType.FLOW.value)
        allowed_tokens = [token.value for token in CatvTokens]
        allowed_search = [search.value for search in CatvSearchType]
        if token_type not in allowed_tokens:
            raise exceptions.ValidationError(f"Invalid token type. Supported: {(', ').join(allowed_tokens)}")
        if search_type not in allowed_search:
            raise exceptions.ValidationError(f"Invalid search type. Supported: {(', ').join(allowed_search)}")
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
        utils_map = {
            CatvSearchType.FLOW.value: {
                'pattern_creator': utils.create_tracking_cache_pattern,
                'history_runner': CatvHistoryTask
            },
            CatvSearchType.PATH.value: {
                'pattern_creator': utils.create_path_cache_pattern,
                'history_runner': CatvPathHistoryTask
            }
        }
        serializer_cls = serializer_map[token_type][search_type]
        serializer = serializer_cls(data=request.data, context={"request": request})
        serializer._token_type = token_type
        serializer.is_valid(raise_exception=True)
        history = serializer.data
        if api_settings.SWITCH_CATV_KAFKA:
            try:
                catv_req_task = CatvRequestTask(api_settings.KAFKA_CATV_TOPIC,
                                                token_type=token_type,
                                                search_type=search_type,
                                                search_params=history,
                                                user=request.user
                                                )
                catv_req_task.run()
                task = catv_req_task.save()
                task_serializer = CATVRequestListSerializer(task)
                return APIResponse({
                    "data": {
                        **task_serializer.data
                    },
                    "messages": {
                        "source": "Address successfully submitted for report generation."
                    }
                })
            except Exception as e:
                print(str(e))
                raise exceptions.ServerError(detail="Something went wrong while submitting your request. Please try again later.")
        else:
            tracking_cache = TrackingCache()
            cache_key = utils_map[search_type]['pattern_creator'](serializer.data)
            history_runner = utils_map[search_type]['history_runner']
            cached_entry = tracking_cache.get_cache_entry(cache_key)
            history.update({'user_id': request.user.id, 'token_type': token_type})
            if not serializer.data.get('force_lookup', False) and cached_entry:
                results = json.loads(gzip.decompress(cached_entry).decode())
                history_runner().run(history=history, from_history=True)
            else:
                results = serializer.get_tracking_results()
                from_db = results["api_calls"] > 0
                tracking_cache.set_cache_entry(cache_key, gzip.compress(json.dumps(results).encode()), 86400)
                history_runner().run(history=history, from_history=from_db)

            catv_metrics = CatvMetrics(results["graph"])
            if history.get("distribution_depth", 0) > 0:
                dist_metrics = catv_metrics.generate_metrics(gt)
                print(dist_metrics)
            if history.get("source_depth", 0) > 0:
                src_metrics = catv_metrics.generate_metrics(lt)
                print(src_metrics)
                
            if "graph" in results and "messages" in results:
                return APIResponse({
                    "data": {**results["graph"]},
                    "messages": {**results["messages"]}
                })
            return APIResponse({
                "data": results
            })


class CATVBTCView(APIView):
    authentication_classes = (CachedTokenAuthentication, )
    permission_classes = (IsAuthenticated, )

    def get_throttles(self):
        if self.request.method.lower() == 'post':
            return [CatvUsageExceededThrottle(), CatvPostThrottle(), ]

    def post(self, request):
        serializer = CATVBTCSerializer(
            data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        history = serializer.data
        if api_settings.SWITCH_CATV_KAFKA:
            try:
                catv_req_task = CatvRequestTask(api_settings.KAFKA_CATV_TOPIC,
                                                token_type=CatvTokens.BTC.value,
                                                search_type=CatvSearchType.FLOW.value,
                                                search_params=history,
                                                user=request.user
                                                )
                catv_req_task.run()
                catv_req_task.save()
                return APIResponse({
                    "data": {},
                    "messages": {
                        "source": "Address successfully submitted for report generation."
                    }
                })
            except:
                raise exceptions.ServerError(detail=f"Something went wrong while submitting your request."
                                             f"Please try again later.")
        else:
            history.update({'user_id': request.user.id, 'token_type': CatvTokens.BTC.value})
            results = serializer.get_tracking_results()
            CatvHistoryTask().delay(history=history, from_history=False)
            if "graph" in results and "messages" in results:
                return APIResponse({
                    "data": {**results["graph"]},
                    "messages": {**results["messages"]}
                })
            return APIResponse({
                "data": results
            })


class CATVBTCTxlistView(APIView):
    authentication_classes = (CachedTokenAuthentication, )
    permission_classes = (IsAuthenticated, )

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
    permission_classes = (IsAuthenticated, )

    def get(self, request):
        serializer = CATVHistorySerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        history_list = []

        if not serializer.data['path_search']:
            model_instance = CatvHistory
            raw_query = Constants.QUERIES["SELECT_USER_CATV_HISTORY"]
        else:
            model_instance = CatvPathHistory
            raw_query = Constants.QUERIES["SELECT_USER_CATV_PATH"]

        history = list(model_instance.objects.raw(raw_query.format(
            request.user.id, request.GET['token_type'].upper())))
        attr_list = [
            'wallet_address', 'distribution_depth', 'source_depth', 'transaction_limit', 'token_address',
            'address_from', 'address_to', 'depth', 'from_date', 'to_date'
        ]
        for item in history:
            history_list.append({attr: getattr(item, attr, None)
                                 for attr in attr_list})
        return APIResponse({
            "data": history_list
        })

class CATVRequestsView(generics.ListAPIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)
    pagination_class = CatvRequestPagination
    filter_backends = (filters.DjangoFilterBackend,)
    
    def list(self, request, *args, **kwargs):
        status = self.request.query_params.get("status", None)
        if status and status not in \
            [CatvTaskStatusType.PROGRESS.value,
             CatvTaskStatusType.RELEASED.value,
             CatvTaskStatusType.FAILED.value]:
            raise exceptions.ValidationError("Invalid status type parameter")
        page = self.request.GET.get("page", 1)
        page = int(page)
        queryset = self.filter_queryset(self.get_queryset(request.user, status))
        page = self.paginate_queryset(queryset)
        serializer = CATVRequestListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
    
    def get_queryset(self, user, status):
        filter_queries = Q(user=user)
        if status:
            filter_queries &= Q(status=status)
        objs = CatvRequestStatus.objects.filter(filter_queries).order_by('-pk')
        print(objs.query)
        return objs

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return self.paginator.get_paginated_response(data, data_key="items")


class CATVReportView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

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
    
    def get(self, request, pk=None):
        obj = self.get_object(pk)
        if not obj.result_file:
            return APIResponse({
                "data": {},
                "messages": {
                    "source": "Results not generated yet. Please try again later."
                }
            })
        file_obj = obj.result_file.file.open(mode="rb")
        buf = file_obj.read()
        results = json.loads(buf.decode("UTF-8"))
        if "messages" in results.keys():
            for k, v in results["messages"].items():
                results["messages"][k] = _(v)
        serializer = CATVRequestListSerializer(obj.request)
        return APIResponse({
            **results,
            "request_params": serializer.data
        })
    
    def put(self, request, pk=None):
        obj = self.get_related_object(pk)
        reverse_token_map = {
            "Ethereum": CatvTokens.ETH.value,
            "Bitcoin": CatvTokens.BTC.value,
            "Tron": CatvTokens.TRON.value,
            "Litecoin": CatvTokens.LTC.value,
            "Ripple": CatvTokens.XRP.value,
            "EOS": CatvTokens.EOS.value,
            "Stellar": CatvTokens.XLM.value,
            "Binance Coin": CatvTokens.BNB.value,
            "Cardano": CatvTokens.ADA.value
        }
        token_type = utils.determine_wallet_type(obj.params.get("wallet_address", obj.params.get("address_from", "")))
        has_from_address = obj.params.get("address_from", "")
        token_type = reverse_token_map[token_type]
        search_type = CatvSearchType.PATH.value if has_from_address else CatvSearchType.FLOW.value
        catv_req_task = CatvRequestTask(api_settings.KAFKA_CATV_TOPIC,
                                        token_type=token_type,
                                        search_type=search_type,
                                        search_params=obj.params,
                                        user=request.user
                                        )
        catv_req_task.run()
        task = catv_req_task.save()
        task_serializer = CATVRequestListSerializer(task)
        return APIResponse({
            "data": {
                **task_serializer.data
            },
            "messages": {
                "source": "Address successfully re-submitted for report generation."
            }
        })

class CATVMultiReportView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_object(self, pk):
        try:
            return CatvResult.objects.select_related('request').get(request__uid__iexact=pk)
        except CatvRequestStatus.DoesNotExist:
            raise exceptions.CATVReportNotFound()
        except CatvResult.DoesNotExist:
            raise exceptions.CATVReportNotFound()

    def get(self, request, pk=None):
        ids = self.request.query_params.get('ids', None)
        finalResult = []
        isDistValue = []
        isSourceValue = []
        if ids is not None:
            mainIds = [x.strip() for x in ids.split(',')]
            for m in mainIds:
                obj = self.get_object(m)
                if not obj.result_file:
                    return APIResponse({
                        "data": {},
                        "messages": {
                            "source": "Results not generated yet. Please try again later."
                        }
                    })
                file_obj = obj.result_file.file.open(mode="rb")
                buf = file_obj.read()
                results = json.loads(buf.decode("UTF-8"))
                if "messages" in results.keys():
                    for k, v in results["messages"].items():
                        results["messages"][k] = _(v)
                serializer = CATVRequestListSerializer(obj.request)
                depthSplited = serializer.data["depth"].split('/')
                isDistValue.append(int(depthSplited[1]))
                isSourceValue.append(int(depthSplited[0]))
                for i in range(len(results["data"]["item_list"])):
                    results["data"]["item_list"][i].update({'id': serializer.data['id']})
                finalResult.extend(results["data"]["item_list"])
        results["data"]["item_list"] = finalResult
        return APIResponse({
            **results,
            "isDistValue": isDistValue,
            "isSourceValue": isSourceValue,
            "request_params": serializer.data
        })

class CATVRequestDetailView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_object(self, request, pk):
        try:
            obj = CatvRequestStatus.objects.get(uid=pk)
            if obj.user != request.user:
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