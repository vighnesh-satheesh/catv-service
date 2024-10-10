import ast
import json
import math
import re
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from json import JSONDecodeError
from time import sleep

import arrow
import requests
from django.core.cache import caches
from django.http import JsonResponse
from ratelimit.utils import is_ratelimited
from requests.exceptions import ConnectTimeout
from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView
from web3 import Web3
from multiprocessing.pool import ThreadPool

from api.catvutils.bloxy_interface import BloxyAPIInterface
from api.rpc.RPCClient import RPCAPIRateFetcher, RPCAPIRequestValidator, RPCClientUpdateUsageCatvCall, \
    RPCClientCATVFetchIndicators
from api.utils import validate_coin, is_eth_based_wallet, serializer_map, build_error_response, string_to_bool
from .constants import Constants
from .exceptions import ServerError
from .models import CatvTokens, CatvSearchType, CatvRequestStatus, CatvTaskStatusType
from .response import APIResponse
from .settings import api_settings
from .validators import bech32
from .validators.coindata import coindata
from .views import submit_catv_request

API_CACHE = caches[api_settings.API_ICF_CACHE]
API_BLOXY_KEY = api_settings.BLOXY_API_KEY
API_ELASTICSEARCH_HOST = api_settings.API_ELASTICSEARCH_HOST
ES_FLAG = api_settings.ES_FLAG
ES_INDEX = api_settings.ES_INDEX
ES_AUTH = api_settings.API_ELASTICSEARCH_CREDENTIALS.split(':')


class HealthCheckView(APIView):
    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        return APIResponse({
            "status": "ok"
        })


class ServerTime(GenericAPIView):
    authentication_classes = ()
    permission_classes = ()

    def get(self, request):
        return JsonResponse({"status": True, "data": {"time": f"{arrow.utcnow().datetime}"}})


def check_es_status():
    global ES_FLAG
    if ES_FLAG:
        try:
            res = requests.head(API_ELASTICSEARCH_HOST, timeout=3)
        except ConnectTimeout:
            ES_FLAG = False
    return ES_FLAG


def consume_key(user_details, key):
    rpc = RPCClientUpdateUsageCatvCall()
    user_rpc = {"id": user_details['user_id'], "token": '', "timestamp": '', 'source': 'api',
                "uid": str(user_details['user_uid']), "credits_required": user_details['credits_required']}
    res = (rpc.call(user_rpc)).decode('UTF-8')
    print("RPCClientUpdateUsageCatvCall() status: ", res)

    if res == 'True':
        API_CACHE.delete(key)
        return True
    else:
        return False


def get_rate(_id, key):
    def __get_key(_id, _key):
        rate = API_CACHE.get(_id)
        if rate:
            try:
                return json.loads(rate)[_key]
            except KeyError:
                return None
        return rate

    # Check if exists in mem cache
    rate = __get_key(f"apiroleinfo_{_id}", key)
    if not rate:
        rpc = RPCAPIRateFetcher()
        user_rpc = {"key": key}
        res = (rpc.call(user_rpc)).decode('UTF-8')
        auth_response = ast.literal_eval(res)
        for i in auth_response:
            API_CACHE.set(
                f"apiroleinfo_{i['role_id']}", json.dumps(i), 60 * 60 * 12)
        return __get_key(_id, key)
    return rate


def check_if_victim_dex(address):
    try:
        addr_query = {"bool": {"must": {"match": {"pattern": address}}, "should": [{"match": {
            "cases": "released"}}, {"match": {"cases": "confirmed"}}]}}
        es_status = check_es_status()
        if es_status:
            # Query from elastic-search
            query = {
                "_source": ["pattern", "annotations", "security_category"],
                "query": {
                    "bool": {
                        "should":
                            addr_query
                    },
                },
                "sort": {
                    "created": {"order": "desc"}
                }
            }
            es_res = requests.post(
                f"{API_ELASTICSEARCH_HOST}/{ES_INDEX}/_search", json=query, auth=tuple(ES_AUTH))
            if not es_res.ok:
                pass
            es_res = [r['_source']
                      for r in es_res.json()['hits']['hits']]
            es_res.reverse()
            annotation_list = es_res[0]["annotations"]
            annotation_list = annotation_list.casefold().split(", ")
            print("check_if_exchange_dex:", annotation_list)
            for annotation in annotation_list:
                if "exchange" in annotation or "dex" in annotation:
                    return True
            return False
        else:
            return False
    except IndexError:
        return False
    except Exception:
        print("Exception in checking whether the address is an exchange/dex: ", traceback.format_exc())
        return False

def _get_token(chain, params):
    token = None
    if chain.upper() in Constants.CATV_API["UTXO_CHAINS"]:
        params.pop('token', None)
    elif chain.upper() in Constants.CATV_API["QUORUM_CHAINS"]:
        if 'token' in params:
            params['symbol'] = params.pop('token', None)
            token = params['symbol']
    else:
        token = params.pop('token', None)
    return token

def catv_query(route, request, chain):
    try:
        source = True
        params = {k: v for k, v in request.GET.items()}
        token = _get_token(chain, params)

        bloxy = BloxyAPIInterface(API_BLOXY_KEY)

        if route == 'outbound':
            source = False
        bloxy_res = bloxy.get_transactions(params['address'], params['limit'],
                                           params['depth_limit'], source, chain,
                                           params['from_date'], params['till_date'], token
                                           )
        if 'errors' in bloxy_res and bloxy_res['errors']:
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)
        addr_list = create_address_list(bloxy_res, chain)
        annotation_dict = fetch_annotations(addr_list, chain)
        bloxy_res = annotate_transactions(bloxy_res, annotation_dict)
        return bloxy_res
    except Exception as e:
        print("Exception in catv_query: ", traceback.format_exc())
        return False


def parse_request_params(request):
    params = {k: v for k, v in request.GET.items()}
    params['query_source'] = params.pop('query_source', False)
    params['txn_hashes'] = params.pop("txn_hashes", [])
    return params


def extract_addresses(params, chain):
    threat_address = params.pop("threat_address", None)
    victim_address = params['address']
    token = _get_token(chain, params)

    return token, threat_address, victim_address


def fetch_transactions(bloxy, params, chain, token, threat_address, victim_address, is_victim_dex):
    address_to_query, source_depth, dist_depth = determine_address_to_use(is_victim_dex, threat_address, victim_address, params['depth_limit'])

    query_source = string_to_bool(params['query_source'])
    if query_source or is_victim_dex:
        return fetch_transactions_with_source(bloxy, params, chain, token, address_to_query, source_depth, dist_depth)
    else:
        # only query dist
        return bloxy.get_transactions(address_to_query, params['limit'],
                                      dist_depth, False, chain,
                                      params['from_date'], params['till_date'], token)


def determine_address_to_use(is_victim_dex, threat_address, victim_address, depth_limit):
    if is_victim_dex and threat_address and threat_address != 'not_available':
        print(f"Using threat_address {threat_address} to query with depths (1,3)")
        return threat_address, 1, 3
    return victim_address, 2, depth_limit


def fetch_transactions_with_source(bloxy, params, chain, token, address, source_depth, dist_depth):
    pool = ThreadPool(processes=2)
    async_bloxy_res_dist = pool.apply_async(
        bloxy.get_transactions, [address, params['limit'],
                                 dist_depth, False, chain, params['from_date'], params['till_date'], token])
    async_bloxy_res_src = pool.apply_async(
        bloxy.get_transactions, [address, params['limit'],
                                 source_depth, True, chain, params['from_date'], params['till_date'], token])
    pool.close()

    bloxy_res_dist = async_bloxy_res_dist.get()
    if 'errors' in bloxy_res_dist:
        pool.terminate()
        pool.join()
        return bloxy_res_dist

    bloxy_res_src = async_bloxy_res_src.get()
    if 'errors' in bloxy_res_src:
        pool.join()
        return bloxy_res_dist

    for item in bloxy_res_src:
        item["depth"] = -1 * item["depth"]

    bloxy_res = [*bloxy_res_src, *bloxy_res_dist]
    pool.join()

    return bloxy_res


def handle_bloxy_errors(bloxy_res):
    standardized_response = build_error_response(bloxy_res)
    return JsonResponse(standardized_response, status=502)


def create_address_list(bloxy_res, chain):
    addr_list = [Web3.to_checksum_address(a['sender']) if is_eth_based_wallet(chain.upper()) else a['sender']
                 for a in bloxy_res] + [
                    Web3.to_checksum_address(a['receiver']) if is_eth_based_wallet(chain.upper()) else a['receiver']
                    for a in bloxy_res]
    return list(set(addr_list))


def fetch_annotations_from_es(addr_list):
    # Split queries into chunks
    chunk_size = 200
    start = 0
    annotation_dict = {}
    addr_query = [{"bool": {"must": {"match": {"pattern": a}}, "should": [{"match": {
        "cases": "released"}}, {"match": {"cases": "confirmed"}}]}} for a in addr_list]
    for a in range(0, math.ceil((len(addr_query) + 1) / chunk_size)):
        # Query from es
        chunked_addr_query = addr_query[start:start + chunk_size]
        query = {
            "size": 10000,
            "_source": ["pattern", "annotations", "security_category"],
            "query": {
                "bool": {
                    "should":
                        chunked_addr_query
                },
            },
            "sort": {
                "created": {"order": "desc"}
            }
        }
        es_res = requests.post(
            f"{API_ELASTICSEARCH_HOST}/{ES_INDEX}/_search", json=query, auth=tuple(ES_AUTH))
        if not es_res.ok:
            pass
        es_res = [r['_source']
                  for r in es_res.json()['hits']['hits']]
        es_res.reverse()
        annotation_dict.update({q['pattern'].lower(): {"annotation": q['annotations'],
                                                       "security_category": q['security_category']} if q[
            'annotations'] else {"annotation": "", "security_category": ""}
                                for q in es_res})
        start = start + chunk_size
    return annotation_dict


def fetch_annotations_from_rpc(addr_list, chain):
    # RPC to fetch indicators from portal-api
    request_dict = {'addr_list': [addr.lower() for addr in addr_list], 'token_type': str(chain.upper())}
    rpc = RPCClientCATVFetchIndicators()
    res = rpc.call(request_dict).decode("utf-8")
    indicators = json.loads(res)
    annotation_dict = {ind['pattern'].lower(): (
        {"annotation": ind['annotation'], "security_category": ind['security_category']} if ind[
            'annotation'] else {"annotation": "", "security_category": ""})
        for ind in indicators}
    return annotation_dict

def fetch_annotations(addr_list, chain):
    es_status = check_es_status()
    if es_status:
        return fetch_annotations_from_es(addr_list)
    else:
        return fetch_annotations_from_rpc(addr_list, chain)


def annotate_transactions(bloxy_res, annotation_dict):
    for d in bloxy_res:
        sender_details = annotation_dict.get(
            d['sender'].lower(), {"annotation": "", "security_category": ""})
        receiver_details = annotation_dict.get(
            d['receiver'].lower(), {"annotation": "", "security_category": ""})
        for i in ['annotation', 'security_category']:
            d[f'sender_{i}'] = sender_details[i]
            d[f'receiver_{i}'] = receiver_details[i]
    return bloxy_res

def ck_query(request, chain):
    try:
        params = parse_request_params(request)
        token, threat_address, victim_address = extract_addresses(params, chain)
        is_victim_dex = check_if_victim_dex(victim_address)

        bloxy = BloxyAPIInterface(API_BLOXY_KEY)
        bloxy_res = fetch_transactions(bloxy, params, chain, token, threat_address, victim_address, is_victim_dex)

        if 'errors' in bloxy_res and bloxy_res['errors']:
            return handle_bloxy_errors(bloxy_res)

        addr_list = create_address_list(bloxy_res, chain)
        annotation_dict = fetch_annotations(addr_list, chain)
        bloxy_res = annotate_transactions(bloxy_res, annotation_dict)

        if not is_victim_dex:
            bloxy_res = filter_exchange_transactions(bloxy_res, "outbound")

        if params['txn_hashes']:
            bloxy_res = filter_transaction_path(bloxy_res, "outbound", params['txn_hashes'])

        return bloxy_res
    except Exception as e:
        print("Exception in catv_query: ", traceback.format_exc())
        return False


def dfs(address, visited, txns_to_remove, graph):
    if address in visited:
        return
    visited.add(address)
    if address in graph:
        for tx_hash, nxt_address in graph[address]:
            txns_to_remove.add(tx_hash)
            dfs(nxt_address, visited, txns_to_remove, graph)


def filter_exchange_transactions(txns, direction):
    graph = defaultdict(set)
    txns_to_remove = set()
    visited = set()
    # Build the graph data
    if direction == 'outbound':
        outer = 'receiver'
        inner = 'sender'
    else:
        outer = 'sender'
        inner = 'receiver'

    for txn in txns:
        address = txn[inner]
        if address not in graph:
            graph[address] = []
        graph[address].append((txn['tx_hash'], txn[outer]))

    for tx in txns:
        nxt_address = tx[outer]
        if 'exchange' in tx.get(f'{outer}_annotation', '').lower():
            dfs(nxt_address, visited, txns_to_remove, graph)

    filtered_txns = [txn for txn in txns if txn['tx_hash'] not in txns_to_remove]

    return filtered_txns


def dfst(address, visited, txns_to_add, graph, address_to_skip):
    
    if address in visited:
        return
    visited.add(address)
    if address in graph:
        for tx_hash, nxt_address in graph[address]:
            txns_to_add.add(tx_hash)
            dfst(nxt_address, visited, txns_to_add, graph, address_to_skip)

def filter_transaction_path(txns, direction, tx_hashes):
    graph = defaultdict(set)
    txns_to_add = set()
    visited = set()
    
    address_to_skip = set()
    # Build the graph data
    if direction == 'outbound':
        outer = 'receiver'
        inner = 'sender'
    else:
        outer = 'sender'
        inner = 'receiver'

    visited.add(txns[0][inner])
    for txn in txns:
        address = txn[inner]
        if txn['tx_hash'] in tx_hashes:
            address_to_skip.add(txn[outer]) 
            txns_to_add.add(txn['tx_hash'])

        if address not in graph:
            graph[address] = []
        graph[address].append((txn['tx_hash'], txn[outer]))
    

    for tx in txns:
        nxt_address = tx[outer]
        if tx.get('tx_hash') in tx_hashes:
            if nxt_address in address_to_skip:
                dfst(nxt_address, visited, txns_to_add, graph, address_to_skip)

    filtered_txns = [txn for txn in txns if txn['tx_hash'] in txns_to_add]

    return filtered_txns

def get_user_details(key):
    def __get_key(key):
        user = API_CACHE.get(key)
        if user:
            try:
                return json.loads(user)
            except KeyError:
                return None
        # return user
        return None

    # Check if exists in mem cache
    rate = __get_key(key)
    if rate is None or rate == "Failed":
        rpc = RPCAPIRequestValidator()
        user_rpc = {"key": key}
        res = (rpc.call(user_rpc)).decode('UTF-8')
        if res != "Failed":
            API_CACHE.set(key, json.dumps(res), 60 * 60 * 12)
        else:
            return None
        return res
    return rate


def validate_key(key, request, rpc_response1):
    def f():
        pass

    # Get the user_id
    try:
        rpc_response = ast.literal_eval(rpc_response1)

        auth = rpc_response['auth']
        api_user_query = rpc_response['api_user'][0]

        if api_user_query['status'] != 'approved':
            return None
        uid = api_user_query['uid']
        user_detail = dict(auth)
        fn = f
        fn.__name__ = request.path_info
        rlm = {
            'GET': {
                'key': 'get:key',
            },
            'POST': {
                'key': 'header:X-Api-Key',
            }
        }

        credits = rpc_response['credits']

        user_detail['catv_count'] = credits['catv_calls']
        user_detail['credits_left'] = credits['credits_left']
        user_detail['credits_required'] = rpc_response['credits_required']
        rate = get_rate(api_user_query['role_id'], 'catv_rate_limit')

        rl = is_ratelimited(request, key=rlm[request.method]['key'], method=request.method,
                            rate=rate, fn=fn, increment=True)

        user_detail['uid'] = uid
        user_detail['ratelimit_status'] = rl
        user_detail['rate_limit'] = rate
        if user_detail['credits_left'] >= 0:
            return user_detail
        return None
    except Exception:
        print("Exception in validate_key: ", traceback.format_exc())
        return None


def validate_request(request, key, rpc_response, required_params_list=None, allowed_param_list=None, check_body=True):
    try:
        if request.method == 'POST' or request.method == 'PUT' or request.method == 'PATCH' or request.method == 'DELETE':
            key_details = validate_key(key, request, rpc_response)
            if not key_details:
                return JsonResponse(Constants.CATV_API_RESPONSE["UNAUTHORIZED"], status=401)
            # if isinstance(key_details, JsonResponse):
            #     return key_details
            if check_body:
                try:
                    request_body = json.loads(request.body)
                except JSONDecodeError:
                    return JsonResponse(Constants.CATV_API_RESPONSE["REQUEST_BODY_MISSING"], status=400)
            if required_params_list:
                missing_params = list(
                    set(required_params_list) - set(list(request_body.keys())))
                if missing_params:
                    return JsonResponse(
                        {"status": False, "data": {"message": f"Missing parameter(s) {', '.join(missing_params)}"}},
                        status=400)
            return key_details
        elif request.method == 'GET':

            key_details = validate_key(key, request, rpc_response)
            if not key_details:
                return JsonResponse(Constants.CATV_API_RESPONSE["UNAUTHORIZED"], status=401)
            if required_params_list:
                missing_params = list(
                    set(required_params_list) - set(list(dict(request.GET).keys())))
                if missing_params:
                    return JsonResponse(
                        {"status": False, "data": {"message": f"Missing parameter(s) {', '.join(missing_params)}"}},
                        status=400)
            if allowed_param_list:
                invalid_params = [p for p in list(dict(request.GET).keys(
                )) if p not in allowed_param_list + required_params_list]
                if invalid_params:
                    return JsonResponse(
                        {"status": False, "data": {"message": f"Invalid parameter(s) {', '.join(invalid_params)}"}},
                        status=400)
            return key_details
    except Exception:
        print("Exception in validate_request: ", traceback.format_exc())
        return None


def validate_addr(addr, chain=None, token=None, is_catv=True):
    try:
        supported_networks = Constants.CATV_API["SUPPORTED_NETWORKS"]
        if not addr:
            return None
        if not chain:
            if addr[:3].lower() != 'bc1' and addr[:2].lower() != '0x' and addr[:1].lower() != '1' and addr[
                                                                                                      :1].lower() != '3':
                return None
            if addr[:2].lower() == '0x':
                # Validate eth
                try:
                    addr = Web3.to_checksum_address(addr)
                    return addr.lower()
                except ValueError:
                    return None
            else:
                # Validate btc
                if addr[:3].lower() == 'bc1':
                    # Handle bech32
                    val = list(bech32.bech32_decode(addr))[0]
                    if val:
                        return addr
                elif addr[:1].lower() == '1' or addr[:1].lower() == '3':
                    val = validate_coin(addr)
                    if val.valid:
                        return addr
                return None
        else:
            if (chain.upper() not in supported_networks) or (not chain):
                return None
            val = bool(re.match(
                coindata[chain.upper()]['networkList'][chain.upper()]['addressRegex'], addr))
            if token and chain.lower() not in Constants.CATV_API["UTXO_CHAINS"] and chain.lower() not in [c for c in
                                                                                                          Constants.CATV_API[
                                                                                                              "QUORUM_CHAINS"]
                                                                                                          if
                                                                                                          c != 'XLM'] and token != '0x0000000000000000000000000000000000000000' and not isinstance(
                token, int):
                # Validates token with assumption that token address is consistent with user address
                token_val = bool(re.match(
                    coindata[chain.upper()]['networkList'][chain.upper()]['addressRegex'], token))
            else:
                token_val = True
            # val = bool(re.match(
            #     coindata[token.upper()]['networkList'][chain.upper()]['addressRegex'], addr))
            if val and token_val:
                return addr
            else:
                return None
    except Exception:
        return None


def update_usage(key, res):
    user_data = ast.literal_eval(res)
    api_user = user_data['api_user'][0]
    user_details = {'user_id': user_data['auth']['user_id'],
                    'user_uid': api_user['uid'], 'credits_required': user_data['credits_required']}

    consume_key(user_details, key)


class CatvOutbound(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        try:
            key = self.request.GET.get('key')
            if not key:
                try:
                    key = request.META['HTTP_X_API_KEY']
                except KeyError:
                    return JsonResponse(Constants.CATV_API_RESPONSE["API_KEY_MISSING"], status=401)
            res = get_user_details(key)
            validated_request = validate_request(request, key, res, required_params_list=[
                'address', 'chain'], allowed_param_list=['key', 'token', 'from_date', 'till_date', 'depth_limit',
                                                         'min_tx_amount', 'limit', 'offset', 'filter_exchange_txns'])
            if isinstance(validated_request, JsonResponse):
                return validated_request
            if not validated_request or validated_request['credits_left'] < validated_request['credits_required']:
                return JsonResponse(Constants.CATV_API_RESPONSE["INSUFFICIENT_CREDIT"], status=402)
            ratelimit_status = validated_request['ratelimit_status']
            if ratelimit_status:
                return JsonResponse({"status": False, "data": {
                    "message": f"Too many requests, your rate limit is {validated_request['rate_limit']}"}}, status=429)
            chain = request.GET.get('chain').upper()
            token = request.GET.get(
                'token', '0x0000000000000000000000000000000000000000')
            if not validate_addr(request.GET.get('address'), chain, token=token, is_catv=True):
                return JsonResponse({"status": False, "data": {"message": f"Invalid address for specified chain"}},
                                    status=400)
            bloxy_res = catv_query('outbound', request, chain)
            if not bloxy_res:
                return JsonResponse(Constants.CATV_API_RESPONSE["NO_DATA_FOUND"], status=500)

            update_usage(key, res)
            return JsonResponse({"status": True, "data": bloxy_res})
        except Exception as e:
            print("Exception in CatvOutbound: ", traceback.format_exc())
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)


class ChainKeeperTransactions(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            key = self.request.GET.get('key')
            if not key:
                try:
                    key = request.META['HTTP_X_API_KEY']
                    print(f"Chainkeeper transactions api call: {key}")
                except KeyError:
                    return JsonResponse(Constants.CATV_API_RESPONSE["API_KEY_MISSING"], status=401)
            chain = request.GET.get('chain').upper()
            bloxy_res = ck_query(request, chain)
            if isinstance(bloxy_res, JsonResponse):
                return bloxy_res
            if not bloxy_res:
                return JsonResponse(Constants.CATV_API_RESPONSE["NO_DATA_FOUND"], status=500)
            return JsonResponse({"status": True, "data": bloxy_res})
        except Exception as e:
            print("Exception in CatvOutbound: ", traceback.format_exc())
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)


class CatvSupportedNetworks(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        try:
            key = self.request.GET.get('key')
            if not key:
                try:
                    key = request.META['HTTP_X_API_KEY']
                except KeyError:
                    return JsonResponse(Constants.CATV_API_RESPONSE["API_KEY_MISSING"], status=401)

            res = get_user_details(key)
            auth = validate_request(request, key, res)

            if isinstance(auth, JsonResponse):
                return auth
            res = [{"chain": n, "tokens": (
                True if n not in [c for c in Constants.CATV_API["UTXO_CHAINS"]] + ['XRP'] else False)} for n in
                   Constants.CATV_API["SUPPORTED_NETWORKS"]]
            return JsonResponse({"status": True, "data": res}, status=200)
        except Exception:
            print("Exception in CatvSupportedNetworks: ", traceback.format_exc())
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)


class ApiKeyInfo(GenericAPIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        try:

            key = self.request.GET.get('key')
            if not key:
                return JsonResponse({"status": False, "data": {"message": "Api key is required"}}, status=401)

            res = get_user_details(key)
            auth = validate_request(request, key, res)
            if isinstance(auth, JsonResponse):
                return auth
            ratelimit_status = auth['ratelimit_status']
            if ratelimit_status:
                return JsonResponse({"status": False, "data": {
                    "message": f"Too many requests, your rate limit is {auth['rate_limit']}"}}, status=429)

            data = {"catv_count": auth['catv_count'], "credits_left": auth['credits_left']}
            return JsonResponse({"status": True, "data": data}, status=200)
        except Exception:
            traceback.print_exc()
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)


class CatvInbound(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, format=None):
        try:
            key = self.request.GET.get('key')
            if not key:
                try:
                    key = request.META['HTTP_X_API_KEY']
                except KeyError:
                    return JsonResponse(Constants.CATV_API_RESPONSE["API_KEY_MISSING"], status=401)
            res = get_user_details(key)
            validated_request = validate_request(request, key, res, required_params_list=[
                'address', 'chain'], allowed_param_list=['key', 'token', 'from_date', 'till_date', 'depth_limit',
                                                         'min_tx_amount', 'limit', 'offset', 'filter_exchange_txns'])
            if isinstance(validated_request, JsonResponse):
                return validated_request
            if not validated_request or validated_request['credits_left'] < validated_request['credits_required']:
                return JsonResponse(Constants.CATV_API_RESPONSE["INSUFFICIENT_CREDIT"], status=402)
            ratelimit_status = validated_request['ratelimit_status']
            if ratelimit_status:
                return JsonResponse({"status": False, "data": {
                    "message": f"Too many requests, your rate limit is {validated_request['rate_limit']}"}}, status=429)
            chain = request.GET.get('chain').upper()
            token = request.GET.get(
                'token', '0x0000000000000000000000000000000000000000')
            if not validate_addr(request.GET.get('address'), chain, token=token, is_catv=True):
                return JsonResponse({"status": False, "data": {"message": f"Invalid address for specified chain"}},
                                    status=400)
            bloxy_res = catv_query('inbound', request, chain)
            if not bloxy_res:
                return JsonResponse(Constants.CATV_API_RESPONSE["NO_DATA_FOUND"], status=500)

            update_usage(key, res)

            return JsonResponse({"status": True, "data": bloxy_res})
        except Exception as e:
            print("Exception in CatvInbound: ", traceback.format_exc())
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)


class CATVReportLinkView(APIView):
    authentication_classes = []
    permission_classes = []
    request_uid = None
    released = False
    failed = False

    def post(self, request):
        try:
            key = request.META['HTTP_X_API_KEY']
        except KeyError:
            return JsonResponse(Constants.CATV_API_RESPONSE["API_KEY_MISSING"], status=401)
        data = request.data
        if not data.get("token_address"):
            data["token_address"] = Constants.CATV_API["DEFAULT_TOKEN_ADDRESS"]
        if not data.get("transaction_limit"):
            data["transaction_limit"] = 2000
        token_type = data.get('token_type', CatvTokens.ETH.value).upper()
        search_type = data.get('search_type', CatvSearchType.FLOW.value)
        serializer_cls = serializer_map[token_type][search_type]
        serializer = serializer_cls(data=data, context={"request": request})
        serializer._token_type = token_type
        serializer.is_valid(raise_exception=True)
        history = serializer.data
        try:
            res = get_user_details(key)
            rpc_response = ast.literal_eval(res)
            auth = rpc_response["auth"]
            request.user = auth
            # Submit CATV request
            catv_sub_res = submit_catv_request(token_type, search_type, history, request, True)
            self.request_uid = catv_sub_res["uid"]
            try:
                self.check_status()
            except TimeoutError:
                return APIResponse({
                    "status": False,
                    "request_uid": self.request_uid,
                    "data": {
                        "message": Constants.CATV_API["CATV_REPORT_TIMED_OUT"]
                    },
                    "request_params": data
                })

            if self.released:
                update_usage(key, res)  # update usage only if released
                return APIResponse({
                    "status": True,
                    "request_uid": self.request_uid,
                    "data": {
                        "report_url": self.get_catv_report_url(),
                        "message": Constants.CATV_API["CATV_REPORT_SUCCESS"]
                    },
                    "request_params": data
                })

            if self.failed:
                return APIResponse({
                    "status": False,
                    "request_uid": self.request_uid,
                    "data": {
                        "message": Constants.CATV_API["CATV_REPORT_FAILED"]
                    },
                    "request_params": data
                })

        except Exception:
            traceback.print_exc()
            raise ServerError(
                detail="Something went wrong while submitting your request. Please try again later.")

    def check_status(self):
        catv_request = CatvRequestStatus.objects.get(uid=self.request_uid)

        timeout_time = datetime.now() + timedelta(minutes=1.5)

        while True:
            if datetime.now() >= timeout_time:
                raise TimeoutError("Polling timed out after 1.5 minutes.")

            catv_request.refresh_from_db()

            if catv_request and catv_request.status == CatvTaskStatusType.PROGRESS:
                print(f"Processing {self.request_uid}...")
                sleep(7)
            elif catv_request.status == CatvTaskStatusType.RELEASED:
                self.released = True
                break
            elif catv_request.status == CatvTaskStatusType.FAILED:
                self.failed = True
                break

    def get_catv_report_url(self):
        return f'{api_settings.CATV_REPORT_BASE_URL}/{self.request_uid}'
