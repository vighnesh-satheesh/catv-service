from rest_framework import exceptions
from rest_framework.views import APIView
from ..models import (
    Case,
    CaseStatus,
    CaseHistory,
    Indicator,
    IndicatorPatternType,
    IndicatorPatternSubtype
)

from django.db.models import Q
from django.db.models.functions import Lower

from .serializers import (
    CasePostSerializer,
    IndicatorPostSerializer,
    IndicatorSimpleListSerializer,
    IndicatorDetailSerializer,
    CaseHistoryPostSerializer,
)

from ..serializers import CaseTRDBSerializer, CATVSerializer
from ..constants import Constants
from .. import utils
from .. import permissions
from ..cache import DefaultCache
from ..response import APIResponse

import json

class CaseIntervalView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.InternalOnly,)
    model = Case

    def post(self, request, format=None):
        serializer = CasePostSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        case = serializer.save()

        # save history.
        history_log = Constants.HISTORY_LOG
        history_log["msg"] = CaseStatus.RELEASED.value if case.status.value == CaseStatus.RELEASED.value else CaseStatus.NEW.value
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

        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])

        return APIResponse({
            "data": {
                "case": {
                    "id": case.pk,
                    "uid": case.uid,
                    "indicators": IndicatorSimpleListSerializer(case.indicators, many=True).data
                }
            }
        })


class IndicatorInternalPostView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.InternalOnly,)
    model = Indicator

    def post(self, request):
        data = request.data
        patterns = data['patterns'] if 'patterns' in data else []
        pattern_type = data['pattern_type'] if 'pattern_type' in data else None
        pattern_subtype = data['pattern_subtype'] if 'pattern_subtype' else None
        security_category = data['security_category'] if 'security_category' in data else None
        security_tags = data['security_tags'] if 'security_tags' in data else None

        if pattern_type is None or pattern_subtype is None or len(patterns) == 0:
            raise exceptions.ValidationError("pattern, pattern_type and pattern_subtype are required")

        filter_queries = Q(cases__status__in=[CaseStatus.RELEASED])

        if security_category:
            filter_queries &= Q(security_category=security_category)
        if patterns:
            filter_queries &= Q(pattern_lower__in=[x.lower() for x in patterns])
        if pattern_type:
            filter_queries &= Q(pattern_type=pattern_type)
        if pattern_subtype:
            filter_queries &= Q(pattern_subtype=pattern_subtype)
        if security_tags:
            filter_queries &= Q(security_tags__arrayilike=security_tags)

        indicators = Indicator.objects.annotate(pattern_lower=Lower('pattern')).filter(filter_queries).distinct('id').order_by('pk')
        result_serializer = IndicatorDetailSerializer(indicators, many=True)

        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])

        return APIResponse({
            "data": result_serializer.data
        })


class IndicatorInternalView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.InternalOnly,)
    model = Indicator

    def post(self, request):
        if "indicators" in request.data:
            serializer = IndicatorPostSerializer(data = request.data["indicators"], many=True)
        else:
            serializer = IndicatorPostSerializer(data = request.data)
        serializer.is_valid(raise_exception=True)
        indicator_obj = serializer.save()
        result_serializer = IndicatorSimpleListSerializer(indicator_obj, many="indicators" in request.data)

        c = DefaultCache()
        c.delete_key(Constants.CACHE_KEY['LEFT_PANEL_VALUES'])
        c.delete_key(Constants.CACHE_KEY['NUMBER_OF_INDICATORS_CASES'])

        return APIResponse({
            "data": result_serializer.data
        })

    def get(self, request):
        filter_queries = Q(cases__status__in=[CaseStatus.RELEASED])
        security_category = request.query_params.get("security_category", None)
        pattern = request.query_params.get('pattern', None)
        patterns = request.GET.getlist("patterns")
        pattern_type = request.query_params.get("pattern_type", None)
        pattern_subtype = request.query_params.get("pattern_subtype", None)
        security_tags = request.GET.getlist("security_tags")

        if pattern_type is None or pattern_subtype is None:
            raise exceptions.ValidationError("pattern_type and pattern_subtype are required")

        try:
            IndicatorPatternType(pattern_type)
        except ValueError:
            raise exceptions.ValidationError("invalid pattern_type")
        try:
            IndicatorPatternSubtype(pattern_subtype)
        except ValueError:
            raise exceptions.ValidationError("invalid pattern_subtype")

        if security_category:
            filter_queries &= Q(security_category=security_category)
        if pattern:
            filter_queries &= Q(pattern__iexact=pattern)
        if patterns:
            filter_queries &= Q(pattern_lower__in=[x.lower() for x in patterns])
        if pattern_type:
            filter_queries &= Q(pattern_type=pattern_type)
        if pattern_subtype:
            filter_queries &= Q(pattern_subtype=pattern_subtype)
        if security_tags:
            filter_queries &= Q(security_tags__arrayilike=security_tags)

        indicators = Indicator.objects.annotate(pattern_lower=Lower('pattern')).filter(filter_queries).distinct('id').order_by('pk')
        result_serializer = IndicatorDetailSerializer(indicators, many=True)
        return APIResponse({
            "data": result_serializer.data
        })


class CATVInternalView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.InternalOnly,)

    def post(self, request):
        serializer = CATVSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        addr_limit = serializer.data.get("transaction_limit", 100000)
        results, api_calls = serializer.get_tracking_results(tx_limit=addr_limit, limit=addr_limit, save_to_db=False)
        return APIResponse({
            "data": results
        })
