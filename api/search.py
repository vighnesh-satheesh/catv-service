"""
Encapsulate search capabilities through ElasticSearch.
"""

from datetime import datetime
import socket

import pytz
from django.db.models import Q
from requests import Request

from .exceptions import CaseFilterError
from .models import UserPermission, User
from .settings import api_settings
from .utils import build_query_string_filter, AsyncAPICaller

__all__ = ('CaseSearchES',)


class CaseSearchES:
    """Class for searching case documents on Elasticsearch"""
    def __init__(self, request):
        self.request = request

    def __make_shared_filter(self, is_user_view=False):
        """
        Build common filter object and do some validation for category and sub-category.
        Like cases=my&status=progress
        """
        case_cate = self.request.GET.get("case", None)
        case_cate = case_cate.split("_")
        if len(case_cate) not in [1, 2]:
            raise CaseFilterError()
        case_filter = Q()
        cate = case_cate[0]
        subcate = None
        if len(case_cate) == 2:
            subcate = case_cate[1]

        if cate not in ["all", "my", "org"]:
            raise CaseFilterError()

        if subcate and subcate not in ["new", "progress", "confirmed", "rejected", "released"]:
            raise CaseFilterError()

        if subcate is not None:
            case_filter &= Q(status=subcate)

        if cate == "all":
            if self.request.user.permission == UserPermission.EXCHANGE and not is_user_view:
                case_filter &= (Q(status="released") | Q(status="confirmed"))
        elif cate == "my":
            case_filter &= (Q(owner=self.request.user.pk) | Q(reporter=self.request.user.pk))
        return case_filter
    
    def __get_es_results(self, query_list, order_key, page):
        """Helper method to make request to search_index viewsets and additional raw count query, if needed."""
        query_string_drf, query_string_raw = build_query_string_filter(query_list)
        print(query_list)
        search_query = self.request.GET.getlist("keyword", [])
        # search_query = next(
        #     (query for query in query_list if query[0] == 'search'), None)
        headers = {
            'X-Forwarded-For': socket.gethostbyname(socket.gethostname())
        }

        if api_settings.ELASTICSEARCH_CREDENTIALS:
            user, pwd = api_settings.ELASTICSEARCH_CREDENTIALS.split(':')
            cred = (user, pwd)
        else:
            cred = None
        
        if query_list:
            es_serializer_req = Request('GET',
                                                url=f'{api_settings.BASE_API_URL}ecsearch/cases/?{query_string_drf}'
                                                f'&ordering={order_key}&page={page}', headers=headers)
            es_raw_req = Request('GET',
                                      f'{api_settings.ELASTICSEARCH_HOST}/{api_settings.ELASTICSEARCH_CASE_IDX}/_count?q={query_string_raw}',
                                      auth=cred)
        else:
            es_serializer_req = Request('GET', url=f'{api_settings.BASE_API_URL}ecsearch/cases/', headers=headers)
            es_raw_req = Request('GET',
                                        f'{api_settings.ELASTICSEARCH_HOST}/{api_settings.ELASTICSEARCH_CASE_IDX}/_count', auth=cred)
        if not search_query:
            async_req_caller = AsyncAPICaller(
                [es_serializer_req, es_raw_req])
        else:
            async_req_caller = AsyncAPICaller([es_serializer_req], 1)
        result = async_req_caller.execute_request_pool()
        return result
    
    def __filter_case_board_es(self):
        """
        Add additional filters from shared filter, and invoke helper method to search on ElasticSearch
        """
        case_filter = self.__make_shared_filter(is_user_view=False)
        keyword_filter = Q()
        
        order_by = self.request.GET.get('order_by', 'id_desc')
        security_category = self.request.GET.getlist("security_category") or []
        pattern_subtype = self.request.GET.getlist("pattern_subtype") or []
        pattern_type = self.request.GET.getlist("pattern_type") or []
        keyword = self.request.GET.getlist("keyword") or []
        start_date = self.request.GET.getlist("start_date") or []
        end_date = self.request.GET.getlist("end_date") or []
        tz = self.request.query_params.get('timezone', None)
        page = self.request.GET.get('page', 1)
        order_by = order_by.split('_')
        key = ''
        if order_by[1] == 'desc':
            key = '-'
        key = key + order_by[0]
        page = int(page)
        
        if len(security_category) > 0:
            case_filter &= Q(security_category__in=security_category)
        if len(pattern_type) > 0:
            case_filter &= Q(pattern_type__in=pattern_type)
        if len(pattern_subtype) > 0:
            case_filter &= Q(pattern_subtype__in=pattern_subtype)
        if len(start_date) > 0:
            start_date = datetime.utcfromtimestamp(int(start_date[0]) / 1000)
            fmt_start_date = start_date.strftime("%Y-%m-%d"'T'"%H:%M:%S")
            case_filter &= Q(updated__gte=fmt_start_date) & Q(created__gte=fmt_start_date)
        if len(end_date) > 0:
            end_date = datetime.utcfromtimestamp(int(end_date[0]) / 1000)
            fmt_end_date = end_date.strftime("%Y-%m-%d"'T'"%H:%M:%S")
            case_filter &= Q(updated__lte=fmt_end_date) & Q(created__lte=fmt_end_date)
        if len(keyword) > 0:
            for k in keyword:
                keyword_filter |= Q(search=k)
            case_filter &= keyword_filter
        case_results = self.__get_es_results(case_filter.children, key, page)
        cases = case_results.get("results", [])
        return {
            "cases": cases,
            "totalItems": case_results.get("totalItems", 0),
            "totalPages": case_results.get("totalPages", 0),
            "pageIndex": case_results.get("pageIndex", 0),
            "actualCount": case_results.get("count", case_results.get("totalItems", 0)),
        }
    
    def __filter_user_board_es(self):
        """Filter for user view"""
        case_filter = self.__make_shared_filter(is_user_view=True)
        usercase_category = self.request.GET.get("user_case", None)
        usercase_category = usercase_category.split('_')
        if not len(usercase_category) == 2:
            raise CaseFilterError()
        user_uid = usercase_category[0]
        action = usercase_category[1]
        try:
            user = User.objects.get(uid=user_uid)
        except User.DoesNotExist:
            raise CaseFilterError()

        if action not in ['reported', 'released']:
            raise CaseFilterError()

        if action == 'reported':
            case_filter &= Q(reporter=user.pk)
        elif action == 'released':
            case_filter &= Q(verifier=user.pk)

        order_by = self.request.GET.get('order_by', 'id_desc')
        page = self.request.GET.get('page', 1)
        order_by = order_by.split('_')
        key = ''
        if order_by[1] == 'desc':
            key = '-'
        key = key + order_by[0]
        page = int(page)
        
        user_case_results = self.__get_es_results(case_filter.children, key, page)
        user_cases = user_case_results.get("results", [])
        return {
            "cases": user_cases,
            "totalItems": user_case_results.get("totalItems", 0),
            "totalPages": user_case_results.get("totalPages", 0),
            "pageIndex": user_case_results.get("pageIndex", 0),
            "actualCount": user_case_results.get("count", user_case_results.get("totalItems", 0)),
        }
    
    def search(self):
        """Main search method which invokes filter methods depending on query params"""
        case_catgeory = self.request.GET.get("case", None)
        usercase_category = self.request.GET.get("user_case", None)
        if case_catgeory and usercase_category:
            return self.__filter_user_board_es()
        return self.__filter_case_board_es()
