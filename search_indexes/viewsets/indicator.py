from django_elasticsearch_dsl_drf.constants import (
    LOOKUP_FILTER_RANGE,
    LOOKUP_QUERY_IN,
    LOOKUP_QUERY_GT,
    LOOKUP_QUERY_GTE,
    LOOKUP_QUERY_LT,
    LOOKUP_QUERY_LTE,
    LOOKUP_FILTER_WILDCARD,
    LOOKUP_QUERY_CONTAINS,
)
from django_elasticsearch_dsl_drf.filter_backends import (
    IdsFilterBackend,
    OrderingFilterBackend,
    DefaultOrderingFilterBackend,
    SearchFilterBackend,
)
from django_elasticsearch_dsl_drf.viewsets import BaseDocumentViewSet
from rest_framework.permissions import AllowAny

from api.multitoken.tokens_auth import CachedTokenAuthentication
from ..documents import IndicatorDocument
from ..filtering import CustomFilteringBackend
from ..pagination import CustomPageNumberPagination
from ..serializers import IndicatorDocumentSerializer

__all__ = ('IndicatorDocumentView',)


class IndicatorDocumentView(BaseDocumentViewSet):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    document = IndicatorDocument
    serializer_class = IndicatorDocumentSerializer
    pagination_class = CustomPageNumberPagination
    lookup_field = 'id'
    filter_backends = [
        CustomFilteringBackend,
        IdsFilterBackend,
        OrderingFilterBackend,
        DefaultOrderingFilterBackend,
        SearchFilterBackend,
    ]
    filter_fields = {
        'id': {
            'field': 'id',
            'lookups': [
                LOOKUP_FILTER_RANGE,
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_GT,
                LOOKUP_QUERY_GTE,
                LOOKUP_QUERY_LT,
                LOOKUP_QUERY_LTE,
            ]
        },
        'security_category': {
            'field': 'security_category.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ],
        },
        'security_tags': {
            'field': 'security_tags.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ]
        },
        'vector': {
            'field': 'vector.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ],
        },
        'environment': {
            'field': 'environment.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ]
        },
        'pattern_type': {
            'field': 'pattern_type.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ],
        },
        'pattern_subtype': {
            'field': 'pattern_subtype.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ],
        },
        'pattern': {
            'field': 'pattern.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_FILTER_WILDCARD,
                LOOKUP_QUERY_CONTAINS,
            ],
        },
        'detail': {
            'field': 'detail.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_FILTER_WILDCARD,
                LOOKUP_QUERY_CONTAINS,
            ],
        },
        'case_status': {
            'field': 'case_status.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ],
        },
        'annotations': {
            'field': 'annotations.lower',
            'lookups': [
                LOOKUP_QUERY_IN,
            ],
        },
    }
    ordering_fields = {
        'id': 'id',
        'created': 'created',
    }
    ordering = ('-id',)
