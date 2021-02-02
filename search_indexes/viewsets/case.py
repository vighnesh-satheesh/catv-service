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
from ..documents import CaseDocument
from ..filtering import CustomFilteringBackend
from ..pagination import CustomPageNumberPagination
from ..search import CustomSearchBackend
from ..serializers import CaseDocumentSerializer

__all__ = ('CaseDocumentView',)


class CaseDocumentView(BaseDocumentViewSet):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)
    document = CaseDocument
    serializer_class = CaseDocumentSerializer
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
        'title',
        'detail',
        'customer_tag',
    }
    filter_fields = {
        'status': {
            'field': 'status.raw',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'security_category': {
            'field': 'security_category.raw',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'pattern_type': {
            'field': 'pattern_type.raw',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'pattern_subtype': {
            'field': 'pattern_subtype.raw',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_QUERY_CONTAINS,
                LOOKUP_FILTER_WILDCARD,
            ],
        },
        'reporter': {
            'field': 'reporter',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_FILTER_RANGE
            ]
        },
        'reporter_info': {
            'field': 'reporter_info',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_FILTER_RANGE
            ]
        },
        'owner': {
            'field': 'owner',
            'lookups': [
                LOOKUP_QUERY_IN,
                LOOKUP_FILTER_RANGE
            ]
        },
        'verifier': {
            'field': 'verifier',
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
        }
    }
    ordering_fields = {
        'id': 'id',
        'created': 'created',
        'updated': 'updated'
    }
    ordering = ('-id',)
    combine_fields = ['reporter', 'owner', 'verifier']
