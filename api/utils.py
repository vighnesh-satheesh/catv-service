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
from .models import (
    CaseStatus, UserPermission, RolePermission,
    PermissionList, get_permission_from_status,
    CatvTokens
)
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

class QueryDictList(dict):
    def __setitem__(self, key: str, value: list) -> None:
        try:
            self[key]
        except KeyError:
            super().__setitem__(key, [])
        self[key].extend(value) if type(value) is list else self[key].append(value)

    def build_query_drf(self, query_operator='=', subquery_joiner='__', query_joiner='&', skip_join_key=['search', 'customer_tag']):
        query_list = []
        for k, v in self.items():
            if k in skip_join_key:
                for term in v:
                    if k == 'search':
                        query_list.append(f'{skip_join_key[0]}{query_operator}{term}')
                    else:
                        query_list.append(f'{skip_join_key[1]}{query_operator}{term}')
            else:
                str_v = [str(val) for val in v]
                query_list.append(f'{k}{query_operator}{subquery_joiner.join(str_v)}')
        return query_joiner.join(query_list)

    def build_query_raw(self, query_operator=':', subquery_joiner=' OR ', query_joiner=' AND ', skip_term_key='search',
                        key_splitter='__'):
        query_list = []
        for k, v in self.items():
            if k == skip_term_key:
                wildcard_v = list(map(lambda t: f'{t}{subquery_joiner}*{t}*', v))
                query_list.append(f'({subquery_joiner.join(wildcard_v)})')
            else:
                str_v = [str(val) for val in v]
                query_list.append(f'({k.split(key_splitter)[0]}{query_operator}{subquery_joiner.join(str_v)})')
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
                print(resp.text)
                return resp.status_code, {}
            return resp.status_code, loads(resp.text)
        except requests.HTTPError as e:
            print(e)
            return 500, {}

    def execute_request_pool(self):
        pool = ThreadPool(processes=self.concurrency)
        resp_list = pool.map(self.make_request, self.api_urls)
        pool.close()
        resp_dict = {}
        for _, resp in resp_list:
            resp_dict = {**resp_dict, **resp}
        return resp_dict

def determine_wallet_type(address_str):
    regex_token_map = {
        "^0x[a-fA-F0-9]{40}$": "Ethereum",
        "^T[a-zA-Z0-9]{21,34}$": "Tron",
        "^([13]|bc1).*[a-zA-Z0-9]{26,35}$": "Bitcoin",
        "^[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}$": "Litecoin",
        "^([13][a-km-zA-HJ-NP-Z1-9]{25,34})|^((bitcoincash:)?(q|p)[a-z0-9]{41})|^((BITCOINCASH:)?(Q|P)[A-Z0-9]{41})$": "Bitcoin Cash",
        "^r[0-9a-zA-Z]{24,34}$": "Ripple",
        "^[1-5a-z.]{12}$": "EOS",
        "^[0-9a-zA-Z]{56}$": "Stellar",
        "^(bnb1)[0-9a-z]{38}$": "Binance Coin",
        "^[0-9a-zA-Z]+$": "Cardano"
    }
    for regex_token in regex_token_map.items():
        pattern = re.compile(regex_token[0])
        if pattern.match(address_str):
            return regex_token[1]
    return "Ethereum"

def pattern_matches_token(address, token_type):
    token_regex_map = {
        CatvTokens.ETH.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.TRON.value: "^T[a-zA-Z0-9]{21,34}$",
        CatvTokens.BTC.value: "^([13]|bc1).*[a-zA-Z0-9]{26,35}$",
        CatvTokens.LTC.value: "^[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}$",
        CatvTokens.BCH.value: "^([13][a-km-zA-HJ-NP-Z1-9]{25,34})|^((bitcoincash:)?(q|p)[a-z0-9]{41})|^((BITCOINCASH:)?(Q|P)[A-Z0-9]{41})$",
        CatvTokens.XRP.value: "^r[0-9a-zA-Z]{24,34}$",
        CatvTokens.EOS.value: "^[1-5a-z.]{12}$",
        CatvTokens.XLM.value: "^[0-9a-zA-Z]{56}$",
        CatvTokens.BNB.value: "^(bnb1)[0-9a-z]{38}$",
        CatvTokens.ADA.value: "^[0-9a-zA-Z]+$"
    }
    pattern = token_regex_map.get(token_type, None)
    if not pattern:
        return false
    return re.compile(pattern).match(address)
