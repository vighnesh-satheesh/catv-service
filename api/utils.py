import time
import urllib.parse
from functools import wraps
import re
import requests
import requests.exceptions as re_exceptions
from datetime import datetime
import random
import socket
import string
from multiprocessing.pool import ThreadPool
from json import loads

from django.db.models import Q
from django.utils import six
from django.utils.encoding import force_text

from rest_framework import exceptions as rf_exceptions
from rest_framework.views import exception_handler

from .response import APIResponse
from .models import CaseStatus, UserPermission, RolePermission, PermissionList, get_permission_from_status
from . import exceptions
from .settings import api_settings


def get_validation_error_detail(data):
    if isinstance(data, list):
        ret = [
            get_validation_error_detail(item) for item in data
        ]
        if len(ret) == 1 and isinstance(ret[0], str):
            ret = ''.join(ret)
        return ret
    elif isinstance(data, dict):
        ret = {
            key: get_validation_error_detail(value)
            for key, value in data.items()
        }
        return ret
    elif isinstance(data, rf_exceptions.ErrorDetail):
        return six.text_type(data).lower()

    text = force_text(data)
    return text


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        message = None
        detail = None
        if (isinstance(exc, rf_exceptions.ValidationError)):
            message = "required fields missing or invalid input."
            detail = get_validation_error_detail(exc.detail)
        else:
            message = str(exc)

        if hasattr(exc, "exc_file_rid"):
            if detail:
                detail["rid"] = exc.exc_file_rid
            else:
                detail = {"rid": exc.exc_file_rid}

        response.data = {
            "error": {
                "code": response.status_code,
                "message": message
            }
        }
        if detail:
            response.data["error"]["detail"] = detail
        response.__class__ = APIResponse
    return response


def get_dashboard_item(category, status, counter):
    cid = "{0}_{1}".format(category, status)
    return {
        "id": cid,
        "count": counter[cid]
    }


def retry(ExceptionToCheck, tries=4, delay=3, backoff=2, logger=None):
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = "%s, Retrying in %d seconds..." % (str(e), mdelay)
                    if logger:
                        logger.warning(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry
    return deco_retry


def validate_dateformat(value, date_format):
    datetime.strptime(value, date_format)


def create_tracking_cache_pattern(data):
    wallet_address = data.get("wallet_address", "")
    source_depth = data.get("source_depth", 0)
    distribution_depth = data.get("distribution_depth", 0)
    transaction_limit = data.get("transaction_limit", 0)
    from_date = data.get("from_date", "")
    to_date = data.get("to_date", "")
    token_address = data.get("token_address", "")

    return 'w{0}s{1}d{2}tx{3}fd{4}td{5}tk{6}'.format(wallet_address, source_depth, distribution_depth,
                                                     transaction_limit, from_date, to_date, token_address)


def create_path_cache_pattern(data):
    address_from = data.get("address_from", "")
    address_to = data.get("address_to", '')
    token_address = data.get("token_address", "")
    depth = data.get("depth", "")
    from_date = data.get("from_date", "")
    to_date = data.get("to_date", "")

    return f"af{address_from}at{address_to}d{depth}fd{from_date}td{to_date}tk{token_address}"


class CaseStatusTransition(object):
    # status, is_owner
    owner_transit = {
        (CaseStatus.NEW, True): [CaseStatus.PROGRESS],
        (CaseStatus.NEW, False): [CaseStatus.PROGRESS],
        (CaseStatus.PROGRESS, True): [CaseStatus.NEW, CaseStatus.CONFIRMED, CaseStatus.REJECTED],
        (CaseStatus.CONFIRMED, True): [CaseStatus.PROGRESS],
        (CaseStatus.REJECTED, True): [CaseStatus.PROGRESS]
    }

    # status, is_owner
    super_transit = {
        (CaseStatus.NEW, True): [CaseStatus.PROGRESS],
        (CaseStatus.NEW, False): [CaseStatus.PROGRESS],
        (CaseStatus.CONFIRMED, True): [CaseStatus.RELEASED, CaseStatus.REJECTED],
        (CaseStatus.RELEASED, True): [CaseStatus.REJECTED]
    }

    def next(self, status, is_super, is_owner, permission):
        super_status = self.super_transit.get((status, is_super), [])
        owner_status = self.owner_transit.get((status, is_owner), [])
        if permission == UserPermission.USER:
            return {}
        else:
            return set(super_status + owner_status)

    def validate(self, status, next_status, is_super, is_owner):
        super_status = self.super_transit.get((status, is_super), [])
        not_super_status = self.super_transit.get((status, not is_super), [])
        owner_status = self.owner_transit.get((status, is_owner), [])
        not_owner_status = self.owner_transit.get((status, not is_owner), [])
        if is_super and is_owner:
            if next_status in super_status or next_status in owner_status:
                return
            else:
                raise exceptions.CaseStatusChangeError(status.value, next_status.value)
        elif is_super and not is_owner:
            if next_status in super_status:
                return
            elif next_status in not_owner_status:
                raise exceptions.OwnerRequiredError()
            else:
                raise exceptions.CaseStatusChangeError(status.value, next_status.value)
        elif not is_super and is_owner:
            if next_status in owner_status:
                return
            elif next_status in not_super_status:
                raise exceptions.SupersentinelRequiredError()
        else:
            if next_status in super_status or next_status in owner_status:
                return
            elif next_status in not_super_status:
                raise exceptions.SupersentinelRequiredError()
            elif next_status in not_owner_status:
                raise exceptions.OwnerRequiredError()
            else:
                raise exceptions.CaseStatusChangeError(status.value, next_status.value)

    def check_access(self, status, role_id):
        action_code = get_permission_from_status(status.value).value
        perm_dict = RolePermission.objects.get_permission_matrix(role_id, action_code)[0]
        if perm_dict[action_code]:
            return
        else:
            raise exceptions.StatusChangeError()


CASE_STATUS_FSM = CaseStatusTransition()


def get_case_next_status(obj, is_super, is_owner):
    if obj.status == CaseStatus.NEW:  # authenticated user. new -> progress. owner becomes user.
        return [CaseStatus.PROGRESS]
    elif obj.status == CaseStatus.PROGRESS:  # only owner. progress -> new, confirmed, rejected.
        if is_owner:
            return [CaseStatus.NEW, CaseStatus.CONFIRMED, CaseStatus.REJECTED]
    elif obj.status == CaseStatus.CONFIRMED:
        if is_super and is_owner:
            return [CaseStatus.PROGRESS, CaseStatus.RELEASED, CaseStatus.REJECTED]
        elif is_super:  # supersentinel. confirmed -> released,rejected
            return [CaseStatus.RELEASED, CaseStatus.REJECTED]
        elif is_owner:  # owner. confirmed -> progress
            return [CaseStatus.PROGRESS]
    elif obj.status == CaseStatus.REJECTED:  # owner. rejected -> progress.
        if is_owner:
            return [CaseStatus.PROGRESS]
    elif obj.status == CaseStatus.RELEASED:  # supersentinel. released -> rejected
        return [CaseStatus.REJECTED]

    return []


class TRDBApiClient(object):
    def __init__(self, base_url=None):
        self.base_url = base_url if base_url else api_settings.TRDB_API_URL
        assert(self.base_url is not None)

    @retry(re_exceptions.ConnectionError, tries=3, delay=1, backoff=1)
    def push_case(self, action, case_data):
        # TODO: retry will fail because of case_data is mutable.
        if case_data is None:
            raise AttributeError("case should not be empty.")
        if action == "activateCase":
            case_data = self.__activate_case_data(case_data)
        elif action == "deactivateCase":
            case_data = self.__deactivate_case_data(case_data)

        data = {
            "action": action,
            "created": int(time.time()),
            "case": case_data
        }

        if api_settings.PORTAL_API_MODE == "production":
            with requests.Session() as s:
                res = s.post(urllib.parse.urljoin(self.base_url, "transaction"), json=data, headers={'Connection': 'close'})
                if res.status_code == requests.codes.ok:
                    return True
                else:
                    return False

    def __activate_case_data(self, case_data):
        return case_data

    def __deactivate_case_data(self, case_data):
        return {
            "id": case_data["id"]
        }


def generate_random_key(key_length):
    v = "".join(random.SystemRandom().choice(string.ascii_letters + string.digits) for _ in range(key_length))
    return v


TRDB_CLIENT = TRDBApiClient()


class QueryDictList(dict):
    def __setitem__(self, key: str, value: list) -> None:
        try:
            self[key]
        except KeyError:
            super().__setitem__(key, [])
        self[key].extend(value) if type(value) is list else self[key].append(value)

    def build_query_drf(self, query_operator='=', subquery_joiner='__', query_joiner='&', skip_join_key='search'):
        query_list = []
        for k, v in self.items():
            if k == skip_join_key:
                for term in v:
                    query_list.append(f'{skip_join_key}{query_operator}{term}')
            else:
                query_list.append(f'{k}{query_operator}{subquery_joiner.join(v)}')
        return query_joiner.join(query_list)

    def build_query_raw(self, query_operator=':', subquery_joiner=' OR ', query_joiner=' AND ', skip_term_key='search',
                        key_splitter='__'):
        query_list = []
        for k, v in self.items():
            if k == skip_term_key:
                wildcard_v = list(map(lambda t: f'{t}{subquery_joiner}*{t}*', v))
                query_list.append(f'({subquery_joiner.join(wildcard_v)})')
            else:
                query_list.append(f'({k.split(key_splitter)[0]}{query_operator}{subquery_joiner.join(v)})')
        return query_joiner.join(query_list)


class AsyncAPICaller:
    def __init__(self, url_list, concurrent=2):
        self.api_urls = url_list
        self.concurrency = concurrent

    def make_request(self, req):
        try:
            s = requests.Session()
            prepped = req.prepare()
            resp = s.send(prepped)
            if resp.status_code != 200:
                return resp.status_code, {}
            return resp.status_code, loads(resp.text)
        except requests.HTTPError:
            return 500, {}

    def execute_request_pool(self):
        pool = ThreadPool(processes=self.concurrency)
        resp_list = pool.map(self.make_request, self.api_urls)
        pool.close()
        resp_dict = {}
        for _, resp in resp_list:
            resp_dict = {**resp_dict, **resp}
        return resp_dict


def build_query_string_filter(query_obj):
    payload = QueryDictList()
    for predicate in query_obj:
        if type(predicate) == Q:
            # this will only happen for keyword search
            for nested_predicate in predicate.children:
                payload[nested_predicate[0]] = [nested_predicate[1]]
        else:
            payload[predicate[0]] = predicate[1]
    query_string_drf = payload.build_query_drf()
    query_string_raw = payload.build_query_raw()
    return query_string_drf, query_string_raw


def es_serialized_search(query_string, page, order_key):
    headers = {
        'X-Forwarded-For': socket.gethostbyname(socket.gethostname())
    }

    es_serializer_req = requests.get(
        url=f'{api_settings.BASE_API_URL}ecsearch/indicators/?{query_string}'
        f'&ordering={order_key}&page={page}',
        headers=headers
    )
    if es_serializer_req.status_code != 200:
        return {}
    return loads(es_serializer_req.text)


def es_raw_search(es_func, query_string, **kwargs):
    if api_settings.ELASTICSEARCH_CREDENTIALS:
        user, pwd = api_settings.ELASTICSEARCH_CREDENTIALS.split(':')
        cred = (user, pwd)
    else:
        cred = None
    if query_string:
        url = f'{api_settings.ELASTICSEARCH_HOST}/{api_settings.ELASTICSEARCH_INDICATOR_IDX}/{es_func}?q={query_string}'
    else:
        url = f'{api_settings.ELASTICSEARCH_HOST}/{api_settings.ELASTICSEARCH_INDICATOR_IDX}/{es_func}'
    
    es_raw_req = requests.get(url=url, auth=cred)
    if es_raw_req.status_code != 200:
        return {
            'count': 0
        }
    return loads(es_raw_req.text)


def determine_wallet_type(address_str):
    pattern_type = "Ethereum"
    btc_pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
    if btc_pattern.match(address_str):
        pattern_type = "Bitcoin"
    return pattern_type
