import ast
import json
import math
import re
import traceback
from collections import deque, defaultdict
from json import JSONDecodeError

import arrow
import requests
from django.core.cache import caches
from django.http import JsonResponse
from ratelimit.utils import is_ratelimited
from requests.exceptions import ConnectTimeout
from rest_framework.generics import GenericAPIView
from rest_framework.views import APIView
from web3 import Web3

from api.catvutils.bloxy_interface import BloxyAPIInterface
from api.rpc.RPCClient import RPCAPIRateFetcher, RPCAPIRequestValidator, RPCClientUpdateUsageCatvCall, \
    RPCClientCATVFetchIndicators
from api.utils import validate_coin, is_eth_based_wallet
from .constants import Constants
from .response import APIResponse
from .settings import api_settings
from .validators import bech32
from .validators.coindata import coindata

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
    user_rpc = {"id": user_details['user_id'], "token": '', "timestamp": '','source':'api',
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
                f"apiroleinfo_{i['role_id']}", json.dumps(i), 60*60*12)
        return __get_key(_id, key)
    return rate


def catv_query(route, request, chain):
    try:
        source = True
        token = None
        params = {k: v for k, v in request.GET.items()}

        if chain.upper() in Constants.CATV_API["UTXO_CHAINS"]:
            params.pop('token', None)
        elif chain.upper() in Constants.CATV_API["QUORUM_CHAINS"]:
            if 'token' in params:
                params['symbol'] = params.pop('token', None)
                token = params['symbol']
        else:
            token = params.pop('token', None)
        filter_exchange_txns = params.pop('filter_exchange_txns', False)
        bloxy = BloxyAPIInterface(API_BLOXY_KEY)
        if route == 'outbound':
            source = False
        bloxy_res = bloxy.get_transactions(params['address'], 50000, params['limit'],
                                                   params['depth_limit'], source, chain,
                                                   params['from_date'], params['till_date'], token
                                                )
        if 'error' in bloxy_res:
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)
        addr_list = [Web3.to_checksum_address(a['sender']) if is_eth_based_wallet(chain.upper()) else a['sender']
                     for a in bloxy_res]+[Web3.to_checksum_address(a['receiver']) if is_eth_based_wallet(chain.upper()) else a['receiver'] for a in bloxy_res]
        addr_list = list(set(addr_list))
        addr_query = [{"bool": {"must": {"match": {"pattern": a}}, "should": [{"match": {
            "cases": "released"}}, {"match": {"cases": "confirmed"}}]}} for a in addr_list]
        es_status = check_es_status()
        if es_status:
            # Split queries into chunks
            chunk_size = 200
            start = 0
            annotation_dict = {}
            for a in range(0, math.ceil((len(addr_query)+1)/chunk_size)):
                # Query from es
                chunked_addr_query = addr_query[start:start+chunk_size]
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
                annotation_dict.update({q['pattern'].lower(): {"annotation": q['annotations'], "security_category": q['security_category']} if q['annotations'] else {"annotation": "", "security_category": ""}
                                        for q in es_res})
                start = start+chunk_size
        else:
            # RPC to fetch indicators from portal-api
            request_dict = {'addr_list': [addr.lower() for addr in addr_list], 'token_type': str(chain.upper())}
            rpc = RPCClientCATVFetchIndicators()
            res = rpc.call(request_dict).decode("utf-8")
            indicators = json.loads(res)
            annotation_dict = {ind['pattern'].lower(): (
                {"annotation": ind['annotation'], "security_category": ind['security_category']} if ind[
                    'annotation'] else {"annotation": "", "security_category": ""})
                               for ind in indicators}
        for d in bloxy_res:
            sender_details = annotation_dict.get(
                d['sender'].lower(), {"annotation": "", "security_category": ""})
            receiver_details = annotation_dict.get(
                d['receiver'].lower(), {"annotation": "", "security_category": ""})
            for i in ['annotation', 'security_category']:
                d[f'sender_{i}'] = sender_details[i]
                d[f'receiver_{i}'] = receiver_details[i]
        #For chainkeeper filter outgoing txns from exchanges
        if filter_exchange_txns:
            print("Filtering txs")
            bloxy_res = filter_exchange_transactions(bloxy_res,route)
            print(f'{len(bloxy_res) = }')
        return bloxy_res
    except Exception as e:
        print("Exception in catv_query: ", traceback.format_exc())
        return False


def dfs(address,visited,txns_to_remove,graph):  
    if address in visited:  
        return  
    visited.add(address)  
    if address in graph:  
        for tx_hash, nxt_address in graph[address]:  
            txns_to_remove.add(tx_hash)  
            dfs(nxt_address,visited,txns_to_remove,graph) 

def filter_exchange_transactions(txns,direction):
    graph = defaultdict(set)
    txns_to_remove = set()
    visited = set() 
    # Build the graph data
    if direction == 'outbound':
        outer = 'receiver'
        inner = 'sender'
    else :
        outer = 'sender'
        inner = 'receiver'
    
    for txn in txns:
        address = txn[inner]  
        if address not in graph:  
            graph[address] = []  
        graph[address].append((txn['tx_hash'], txn[outer]))  

    for tx in txns:  
        nxt_address = tx[outer]  
        if 'exchange' in tx.get(f'{outer}_annotation','').lower():
            dfs(nxt_address,visited,txns_to_remove,graph) 
  
    filtered_txns = [txn for txn in txns if txn['tx_hash'] not in txns_to_remove]

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
            API_CACHE.set(key, json.dumps(res), 60*60*12)
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
                    set(required_params_list)-set(list(request_body.keys())))
                if missing_params:
                    return JsonResponse({"status": False, "data": {"message": f"Missing parameter(s) {', '.join(missing_params)}"}}, status=400)
            return key_details
        elif request.method == 'GET':

            key_details = validate_key(key, request, rpc_response)
            if not key_details:
                return JsonResponse(Constants.CATV_API_RESPONSE["UNAUTHORIZED"], status=401)
            if required_params_list:
                missing_params = list(
                    set(required_params_list)-set(list(dict(request.GET).keys())))
                if missing_params:
                    return JsonResponse({"status": False, "data": {"message": f"Missing parameter(s) {', '.join(missing_params)}"}}, status=400)
            if allowed_param_list:
                invalid_params = [p for p in list(dict(request.GET).keys(
                )) if p not in allowed_param_list+required_params_list]
                if invalid_params:
                    return JsonResponse({"status": False, "data": {"message": f"Invalid parameter(s) {', '.join(invalid_params)}"}}, status=400)
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
            if addr[:3].lower() != 'bc1' and addr[:2].lower() != '0x' and addr[:1].lower() != '1' and addr[:1].lower() != '3':
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
            if token and chain.lower() not in Constants.CATV_API["UTXO_CHAINS"] and chain.lower() not in [c for c in Constants.CATV_API["QUORUM_CHAINS"] if c != 'XLM'] and token != '0x0000000000000000000000000000000000000000' and not isinstance(token, int):
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
            # res = get_user_details(key)
            # validated_request = validate_request(request,  key, res,required_params_list=[
            #     'address', 'chain'], allowed_param_list=['key', 'token', 'from_date', 'till_date', 'depth_limit', 'min_tx_amount', 'limit', 'offset'])
            # if isinstance(validated_request, JsonResponse):
            #     return validated_request
            # if not validated_request or validated_request['credits_left'] < validated_request['credits_required']:
            #     return JsonResponse(Constants.CATV_API_RESPONSE["INSUFFICIENT_CREDIT"], status=402)
            # ratelimit_status = validated_request['ratelimit_status']
            # if ratelimit_status:
            #     return JsonResponse({"status": False, "data": {"message": f"Too many requests, your rate limit is {validated_request['rate_limit']}"}}, status=429)
            chain = request.GET.get('chain').upper()
            token = request.GET.get(
                'token', '0x0000000000000000000000000000000000000000')
            # if not validate_addr(request.GET.get('address'), chain, token=token, is_catv=True):
            #     return JsonResponse({"status": False, "data": {"message": f"Invalid address for specified chain"}}, status=400)
            bloxy_res = catv_query('outbound', request, chain)
            if not bloxy_res:
                return JsonResponse(Constants.CATV_API_RESPONSE["NO_DATA_FOUND"], status=500)
            
            # user_data = ast.literal_eval(res)
            # api_user = user_data['api_user'][0]
            # user_details = {'user_id': user_data['auth']['user_id'],
            #                 'user_uid': api_user['uid'], 'credits_required': user_data['credits_required']}
            #
            # consume_key(user_details, key)
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
                True if n not in [c for c in Constants.CATV_API["UTXO_CHAINS"]]+['XRP'] else False)} for n in Constants.CATV_API["SUPPORTED_NETWORKS"]]
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
                return JsonResponse({"status": False, "data": {"message": f"Too many requests, your rate limit is {auth['rate_limit']}"}}, status=429)
            
            data = {"catv_count": auth['catv_count'],"credits_left": auth['credits_left']}
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
            # res = get_user_details(key)
            # validated_request = validate_request(request,  key, res, required_params_list=[
            #     'address', 'chain'], allowed_param_list=['key', 'token', 'from_date', 'till_date', 'depth_limit', 'min_tx_amount', 'limit', 'offset', 'filter_exchange_txns'])
            # if isinstance(validated_request, JsonResponse):
            #     return validated_request
            # if not validated_request or validated_request['credits_left'] < validated_request['credits_required']:
            #     return JsonResponse(Constants.CATV_API_RESPONSE["INSUFFICIENT_CREDIT"], status=402)
            # ratelimit_status = validated_request['ratelimit_status']
            # if ratelimit_status:
            #     return JsonResponse({"status": False, "data": {"message": f"Too many requests, your rate limit is {validated_request['rate_limit']}"}}, status=429)
            chain = request.GET.get('chain').upper()
            token = request.GET.get(
                'token', '0x0000000000000000000000000000000000000000')
            # if not validate_addr(request.GET.get('address'), chain, token=token, is_catv=True):
            #     return JsonResponse({"status": False, "data": {"message": f"Invalid address for specified chain"}}, status=400)
            bloxy_res = catv_query('inbound', request, chain)
            if not bloxy_res:
                return JsonResponse(Constants.CATV_API_RESPONSE["NO_DATA_FOUND"], status=500)
            # user_data = ast.literal_eval(res)
            # api_user = user_data['api_user'][0]
            # user_details = {'user_id': user_data['auth']['user_id'],
            #                 'user_uid': api_user['uid'], 'credits_required': user_data['credits_required']}
            #
            # consume_key(user_details, key)
            return JsonResponse({"status": True, "data": bloxy_res})
        except Exception as e:
            print("Exception in CatvInbound: ", traceback.format_exc())
            return JsonResponse(Constants.CATV_API_RESPONSE["INTERNAL_SERVER_ERROR"], status=500)
