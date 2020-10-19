"""
Encapsulate search capabilities through ElasticSearch.
"""

from datetime import datetime
import socket

import pytz
from django.db.models import Q
from requests import Request

from .exceptions import CaseFilterError
from .models import (
    UserPermission, User, Organization,
    OrganizationUser, OrganizationUserStatus,
    UserRoles
)
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
            case_filter &= Q(status__in=[subcate])

        if cate == "all":
            if self.request.user.permission == UserPermission.EXCHANGE and not is_user_view:
                case_filter &= (Q(status__in=["released", "confirmed"]))
        elif cate == "my":
            case_filter &= (Q(owner=self.request.user.pk) | Q(reporter=self.request.user.pk))
        elif cate == 'org':
            user_list = []
            org_admin = Organization.objects.filter(
                administrator=self.request.user.pk).values_list('id', flat=True)
            member_orgs = OrganizationUser.objects.filter(
                user=self.request.user.pk, status=OrganizationUserStatus.ACTIVE).values_list('organization_id', flat=True)
            if org_admin:
                user_list.extend(
                    OrganizationUser.objects.filter(organization__in=org_admin, status=OrganizationUserStatus.ACTIVE).\
                        values_list('user_id', flat=True)
                )
                user_list.append(self.request.user.pk)
            elif member_orgs:
                user_list.extend(
                    Organization.objects.filter(pk__in=member_orgs).\
                        values_list('administrator', flat=True)
                )
                user_list.extend(
                    OrganizationUser.objects.filter(organization__administrator__in=user_list).\
                        values_list('user_id', flat=True)
                )
            if user_list:
                for user in user_list:
                    case_filter &= Q(owner__in=user)
                    case_filter &= Q(reporter__in=user)
            else:
                case_filter &= Q(owner__in=self.request.user.pk)
                case_filter &= Q(reporter__in=self.request.user.pk)
        return case_filter
    
    def __get_es_results(self, query_list, order_key, page):
        """Helper method to make request to search_index viewsets and additional raw count query, if needed."""
        query_string_drf, query_string_raw = build_query_string_filter(query_list)
        print(query_list)
        headers = {
            'X-Forwarded-For': socket.gethostbyname(socket.gethostname())
        }
        if query_list:
            es_serializer_req = Request('GET',
                                                url=f'{api_settings.SEARCH_BACKEND_URL}ecsearch/cases/?{query_string_drf}'
                                                f'&ordering={order_key}&page={page}', headers=headers)
        else:
            es_serializer_req = Request('GET', url=f'{api_settings.SEARCH_BACKEND_URL}ecsearch/cases/', headers=headers)
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
            if tz is not None:
                aware_start = start_date.replace(tzinfo=pytz.timezone('UTC')).astimezone(pytz.timezone(tz))
            else:
                aware_start = start_date.replace(tzinfo=pytz.timezone('UTC'))
            fmt_start_date = str(datetime.timestamp(aware_start) * 1000)
            case_filter &= Q(updated__gte=fmt_start_date) & Q(created__gte=fmt_start_date)
        if len(end_date) > 0:
            end_date = datetime.utcfromtimestamp(int(end_date[0]) / 1000)
            if tz is not None:
                aware_end = end_date.replace(tzinfo=pytz.timezone('UTC')).astimezone(pytz.timezone(tz))
            else:
                aware_end = end_date.replace(tzinfo=pytz.timezone('UTC'))
            fmt_end_date = str(datetime.timestamp(aware_end) * 1000)
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
            "actualCount": case_results.get("actual_count", 0),
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

        if user != self.request.user and self.request.user.role.role_name != UserRoles.SUPERSENTINEL.value:
            user_case_results = {}
            user_cases = []
        else:
            user_case_results = self.__get_es_results(case_filter.children, key, page)
            user_cases = user_case_results.get("results", [])
        return {
            "cases": user_cases,
            "totalItems": user_case_results.get("totalItems", 0),
            "totalPages": user_case_results.get("totalPages", 0),
            "pageIndex": user_case_results.get("pageIndex", 0),
            "actualCount": user_case_results.get("actual_count", 0),
        }
    
    def search(self):
        """Main search method which invokes filter methods depending on query params"""
        case_catgeory = self.request.GET.get("case", None)
        usercase_category = self.request.GET.get("user_case", None)
        if case_catgeory and usercase_category:
            return self.__filter_user_board_es()
        return self.__filter_case_board_es()
