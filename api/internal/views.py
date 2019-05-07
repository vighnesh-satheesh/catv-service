from rest_framework.views import APIView
from ..models import (
    Case,
    CaseStatus,
    Indicator,
    IndicatorPatternType,
    IndicatorPatternSubtype
)

from django.db.models import Q
from .serializers import (
    CasePostSerializer,
    IndicatorPostSerializer,
    IndicatorSimpleListSerializer,
    IndicatorDetailSerializer
)

from rest_framework import exceptions
from ..response import APIResponse
from .. import permissions
from functools import reduce
from ..cache.indicator import IndicatorCache

class CaseIntervalView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.InternalOnly,)
    model = Case

    def post(self, request, format=None):
        serializer = CasePostSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        case = serializer.save()
        return APIResponse({
            "data": {
                "case": {
                    "id": case.pk,
                    "uid": case.uid,
                    "indicators": IndicatorSimpleListSerializer(case.indicators, many=True).data
                }
            }
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

        """
        if patterns:
            for p in patterns:
                if not IndicatorCache().get_indicator(p.lower()):
                    patterns.remove(p)
        """

        if security_category:
            filter_queries &= Q(security_category=security_category)
        if pattern:
            filter_queries &= Q(pattern__iexact=pattern)
        if patterns:
            filter_queries &= reduce(lambda q, p: q|Q(pattern__iexact=p), patterns, Q())
        if pattern_type:
            filter_queries &= Q(pattern_type=pattern_type)
        if pattern_subtype:
            filter_queries &= Q(pattern_subtype=pattern_subtype)
        if security_tags:
            filter_queries &= Q(security_tags__icontains=security_tags)

        indicators = Indicator.objects.filter(filter_queries).distinct('id').order_by('pk')
        result_serializer = IndicatorDetailSerializer(indicators, many=True)
        return APIResponse({
            "data": result_serializer.data
        })
