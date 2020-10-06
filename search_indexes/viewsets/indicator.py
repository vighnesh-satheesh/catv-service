from django_elasticsearch_dsl_drf.constants import (
    LOOKUP_QUERY_IN,
    LOOKUP_FILTER_WILDCARD,
    LOOKUP_QUERY_CONTAINS,
    LOOKUP_FILTER_RANGE,
    LOOKUP_QUERY_GTE,
    LOOKUP_QUERY_LTE
)
from django_elasticsearch_dsl_drf.filter_backends import (
    IdsFilterBackend,
    OrderingFilterBackend,
    DefaultOrderingFilterBackend,
)
from django_elasticsearch_dsl_drf.viewsets import BaseDocumentViewSet
from rest_framework.permissions import AllowAny

from api.multitoken.tokens_auth import CachedTokenAuthentication
from ..documents import IndicatorDocument
from ..filtering import CustomFilteringBackend
from ..pagination import CustomPageNumberPagination
from ..search import CustomSearchBackend
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
        CustomSearchBackend,
    ]
    search_fields = {
        'pattern'
        # 'pattern': {'boost': 4},
        # 'detail': {'boost': 2},
        # 'annotations': {'boost': 1}
    }
    filter_fields = {
        'security_category': {
            'field': 'security_category',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'security_tags': {
            'field': 'security_tags',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ]
        },
        'vector': {
            'field': 'vector',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'environment': {
            'field': 'environment',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ]
        },
        'pattern_type': {
            'field': 'pattern_type',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'pattern_subtype': {
            'field': 'pattern_subtype',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'cases': {
            'field': 'cases',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'user_id': {
            'field': 'user_id',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_FILTER_RANGE
            ]
        },
        'created': {
            'field': 'created',
            'lookups': [
                LOOKUP_FILTER_RANGE,
                LOOKUP_QUERY_GTE,
                LOOKUP_QUERY_LTE
            ]
        },
        'updated': {
            'field': 'updated',
            'lookups': [
                LOOKUP_FILTER_RANGE,
                LOOKUP_QUERY_GTE,
                LOOKUP_QUERY_LTE
            ]
        },
        'id': {
            'field': 'id',
            'lookups': [
                LOOKUP_FILTER_RANGE,
                LOOKUP_QUERY_GTE,
                LOOKUP_QUERY_LTE
            ]
        }
    }
    ordering_fields = {
        'id': 'id',
        'created': 'created',
        'updated': 'updated'
    }
    ordering = ('-id',)
