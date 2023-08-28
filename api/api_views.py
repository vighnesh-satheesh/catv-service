import ast
import datetime
import json
import math
import os
import re
import traceback
import coinaddr
from operator import gt, lt
from django.http import JsonResponse
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
import requests
from django.core.cache import caches
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from requests.exceptions import ConnectTimeout
from api.catvutils.bloxy_interface import BloxyAPIInterface
from api.rpc.RPCClient import RPCAPIRateFetcher, RPCAPIRequestValidator, RPCClientUpdateUsageCatvCall
from .validators import bech32
from .validators.coindata import coindata
from json import JSONDecodeError
from ratelimit.utils import is_ratelimited
from .settings import api_settings
from .models import (
    ApiIndicator, ApiKey, ApiUsage
)
from .multitoken.tokens_auth import CachedTokenAuthentication
from .response import APIResponse

from web3 import Web3

class HealthCheckView(APIView):
    authentication_classes = (CachedTokenAuthentication,)
    permission_classes = (AllowAny,)

    def get(self, request):
        return APIResponse({
            "status": "ok"
        })
    

API_CACHE = caches[api_settings.API_ICF_CACHE]


def check_es_status():
    global ES_FLAG
    if ES_FLAG:
        try:
            res = requests.head(API_ELASTICSEARCH_HOST, timeout=3)
        except ConnectTimeout:
            ES_FLAG = False
    return ES_FLAG

w3 = Web3(Web3.HTTPProvider(
    "https://mainnet.infura.io/v3/c3cddab6058f4f2fa6e0b60d2a4fd670"))


def consume_key(user_details,key):

    rpc = RPCClientUpdateUsageCatvCall()
    user_rpc = {"id": user_details['user_id'], "token": '', "timestamp": '','source':'api',
                "uid": str(user_details['user_uid'])}
    res = (rpc.call(user_rpc)).decode('UTF-8')
    print("Submission Status: ", res)

    if res == 'True':
        API_CACHE.delete(key)
        return True
    else:
        return False


SUPPORTED_NETWORKS = ['BTC', 'ETH', 'LTC', 'TRX',
                      'EOS', 'XLM', 'ADA', 'BNB', 'BCH', 'XRP', 'BSC', 'KLAY']
QUORUM_CHAINS = ['XRP', 'XLM']
CATV_SUPPORTED_NETWORKS = ['BTC', 'ETH',
                           'LTC', 'TRX', 'BCH', 'XRP', 'XLM', 'EOS', 'ADA', 'BNB', 'BSC', 'KLAY']
EXCEPTION_MAP = {'XRP': 'ripple', 'XLM': 'stellar',
                 'ADA': 'cardano', 'BNB': 'binance'}
SUPPORTED_TOKENS_NETWORK = {c: [n for n in list(
    coindata[c]['networkList'].keys()) if n == c] for c in SUPPORTED_NETWORKS}
BLOXY_CHAIN_MAP = {c: c.lower() for c in list(
    set(SUPPORTED_NETWORKS+CATV_SUPPORTED_NETWORKS))if c not in EXCEPTION_MAP.keys()}

CATV_SUPPORTED_NETWORKS = ['BTC', 'ETH',
                           'LTC', 'TRX', 'BCH', 'XRP', 'XLM', 'EOS', 'ADA', 'BNB', 'BSC', 'KLAY']
UTXO_CHAINS = ['BTC', 'LTC', 'BCH', 'ADA']
UNAUTHORIZED = {"status": False, "data": {
    "message": "Api key invalid or expired"}}
INTERNAL_SERVER_ERROR = {"status": False,
                         "data": {"message": "Internal server error"}}
REQUIRED_HEADERS_MISSING = {"status": False, "data": {
    "message": "Required headers are missing"}}
INSUFFICIENT_CREDIT = {"status": False,
                       "data": {"message": "Insufficient credit"}}
REQUEST_BODY_MISSING = {"status": False,
                        "data": {"message": "Unable to parse body"}}
API_KEY_MISSING = {"status": False, "data": {"message": "Api key required"}}
API_BLOXY_KEY = os.environ['API_BLOXY_KEY']
BLOXY_UTXO_ENDPOINT = "https://sentinel.api.bitquery.io/bitcoin:coinpath"
BLOXY_QUORUM_ENDPOINT = "https://sentinel.api.bitquery.io/ripple:sentinel"
BLOXY_ENDPOINT = "https://sentinel.api.bitquery.io/coinpath"
API_ELASTICSEARCH_HOST = os.environ['API_ELASTICSEARCH_HOST']
ES_FLAG = True
env = os.environ.get("CATVMS_API_ENV")
ES_INDEX = 'dev_latest_indicator'
if(env == 'production'):
    ES_INDEX = 'latest_indicator'

rate_limit_mapping = {
    'GET': {
        'key': 'get:key',
    },
    'POST': {
        'key': 'header:X-Api-Key',
    }
}
ES_AUTH = os.environ['API_ELASTICSEARCH_CREDENTIALS'].split(':')

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
        print("Getting rate from DB")
        rpc = RPCAPIRateFetcher()
        user_rpc = {"key": key}
        res = (rpc.call(user_rpc)).decode('UTF-8')
        auth_response = ast.literal_eval(res)
        print("RESPONSE:", auth_response)
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
        if chain.upper() in UTXO_CHAINS:
            params.pop('token', None)
   
        elif chain.upper() in QUORUM_CHAINS:
            if 'token' in params:
                params['symbol'] = params.pop('token', None)
                token = params['symbol']

        bloxy = BloxyAPIInterface(API_BLOXY_KEY)
        if(route == 'outbound'):
            source = False
        bloxy_res = bloxy.get_transactions(params['address'], 50000, params['limit'],
                                                   params['depth_limit'], source, params['chain'],
                                                   params['from_date'], params['till_date'], token
                                                )
        if 'error' in bloxy_res:
            print(f"bloxy error: {bloxy_res}")
            return JsonResponse(INTERNAL_SERVER_ERROR, status=500)
        addr_list = [w3.toChecksumAddress(a['sender']) if chain.upper() == 'ETH' else a['sender']
                     for a in bloxy_res]+[w3.toChecksumAddress(a['receiver']) if chain.upper() == 'ETH' else a['receiver'] for a in bloxy_res]
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
            # Query from pg

            addr_query = Q()
            for a in addr_list:
                q = {"pattern__iexact": a, "pattern_subtype": chain.upper()}
                addr_query = addr_query | Q(
                    **q, case_id__status__in=['confirmed', 'released'])
            queryset = ApiIndicator.objects.filter(pattern__in=addr_list, pattern_subtype=chain.upper()).distinct('pattern').order_by(
                'pattern', '-created').only('pattern', 'annotation').values('pattern', 'annotation', 'security_category')
            annotation_dict = {q['pattern'].lower(): ({"annotation": q['annotation'], "security_category": q['security_category']} if q['annotation'] else {"annotation": "", "security_category": ""})
                               for q in queryset}
        # Annotate bloxy result
        for d in bloxy_res:
            sender_details = annotation_dict.get(
                d['sender'].lower(), {"annotation": "", "security_category": ""})
            receiver_details = annotation_dict.get(
                d['receiver'].lower(), {"annotation": "", "security_category": ""})
            for i in ['annotation', 'security_category']:
                d[f'sender_{i}'] = sender_details[i]
                d[f'receiver_{i}'] = receiver_details[i]
        return bloxy_res
    except Exception as e:
        print("Exception in catv_query: ", traceback.format_exc())
        return False
    
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
    if not rate: #todo check this ?
        print("Getting rate from rpc")
        rpc = RPCAPIRequestValidator()
        user_rpc = {"key": key}
        res = (rpc.call(user_rpc)).decode('UTF-8')
        #auth_response = ast.literal_eval(res)
        API_CACHE.set(key, json.dumps(res), 60*60*12)
        # return __get_key(key)
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
        rlm = rate_limit_mapping

        api_count = rpc_response['api_count']
        print("api_count : ", api_count)
        is_subscribed = api_user_query['is_subscribed'] if 'is_subscribed' in api_user_query else False
        print("subscribed user making  api call ? ", is_subscribed)
        catv_count_key = 'subscribed_user_calls' if is_subscribed else 'catv_calls'
        catv_left_count_key = 'subscribed_user_calls_left' if is_subscribed else 'catv_calls_left_y'

        user_detail['catv_count'] = api_count[catv_count_key]
        user_detail['api_calls_left'] = int(api_count['subscribed_user_calls_left']) if is_subscribed else int(api_count['catv_calls_left_y'])+int(api_count['catv_calls_left'])

        api_count = api_count[catv_left_count_key]
        if request.path_info == '/submit_report':
            rate = get_rate(
                api_user_query['role_id'], 'cara_submit_rate_limit')
        else:
            rate = get_rate(api_user_query['role_id'], 'cara_rate_limit')

        # Uncomment to block community users who aren't on mobile
        # if rate == 'communityuser' and not parse_user_agent(request.headers['User-Agent']).is_mobile:
        #     return None

        rl = is_ratelimited(request, key=rlm[request.method]['key'], method=request.method,
                            rate=rate, fn=fn, increment=True)

        user_detail['uid'] = uid
        user_detail['ratelimit_status'] = rl
        # rlm[request.method]['ratelimit'][user_role.role_name]
        user_detail['rate_limit'] = rate
        if api_count >= 0:
            return user_detail
        return None
    except Exception:
        print("Exception in validate_key: ", traceback.format_exc())
        return None


def validate_request(request, key, rpc_response, required_params_list=None, allowed_param_list=None, check_body=True):
    try:
        print("Coming into validate_request")
        if request.method == 'POST' or request.method == 'PUT' or request.method == 'PATCH' or request.method == 'DELETE':
            key_details = validate_key(key, request, rpc_response)
            if not key_details:
                return JsonResponse(UNAUTHORIZED, status=401)
            # if isinstance(key_details, JsonResponse):
            #     return key_details
            if check_body:
                try:
                    request_body = json.loads(request.body)
                except JSONDecodeError:
                    return JsonResponse(REQUEST_BODY_MISSING, status=400)
            if required_params_list:
                missing_params = list(
                    set(required_params_list)-set(list(request_body.keys())))
                if missing_params:
                    return JsonResponse({"status": False, "data": {"message": f"Missing parameter(s) {', '.join(missing_params)}"}}, status=400)
            return key_details
        elif request.method == 'GET':

            key_details = validate_key(key, request, rpc_response)
            if not key_details:
                return JsonResponse(UNAUTHORIZED, status=401)
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
        print("Coming into validate_addr")
        sn = SUPPORTED_NETWORKS
        st = SUPPORTED_TOKENS_NETWORK
        if not addr:
            return None
        if not chain:
            if addr[:3].lower() != 'bc1' and addr[:2].lower() != '0x' and addr[:1].lower() != '1' and addr[:1].lower() != '3':
                return None
            if addr[:2].lower() == '0x':
                # Validate eth
                try:
                    addr = w3.toChecksumAddress(addr)
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
                    val = coinaddr.validate('btc', addr.encode())
                    if val.valid:
                        return addr
                return None
        else:
            if (chain.upper() not in sn) or (not chain):
                return None
            val = bool(re.match(
                coindata[chain.upper()]['networkList'][chain.upper()]['addressRegex'], addr))
            if token and chain.lower() not in UTXO_CHAINS and chain.lower() not in [c for c in QUORUM_CHAINS if c != 'XLM'] and token != '0x0000000000000000000000000000000000000000' and not isinstance(token, int):
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
            try:
                key = request.META['HTTP_X_API_KEY']
            except Exception:
                return JsonResponse(API_KEY_MISSING, status=401)
            res = get_user_details(key)
            validated_request = validate_request(request,  key, res,required_params_list=[
                'address', 'chain'], allowed_param_list=['key', 'token', 'from_date', 'till_date', 'depth_limit', 'min_tx_amount', 'limit', 'offset'])
            if isinstance(validated_request, JsonResponse):
                return validated_request
            if not validated_request or validated_request['api_calls_left'] < 1:
                return JsonResponse(INSUFFICIENT_CREDIT, status=402)
            ratelimit_status = validated_request['ratelimit_status']
            if ratelimit_status:
                return JsonResponse({"status": False, "data": {"message": f"Too many requests, your rate limit is {validated_request['rate_limit']}"}}, status=429)
            chain = request.GET.get('chain').upper()
            token = request.GET.get(
                'token', '0x0000000000000000000000000000000000000000')
            if not validate_addr(request.GET.get('address'), chain, token=token, is_catv=True):
                return JsonResponse({"status": False, "data": {"message": f"Invalid address for specified chain"}}, status=400)
            bloxy_res = catv_query('outbound', request, chain)
            if bloxy_res == False:
                return JsonResponse(INTERNAL_SERVER_ERROR, status=500)
            
            user_data = ast.literal_eval(res)
            api_user = user_data['api_user'][0]
            user_details = {'user_id': user_data['auth']['user_id'],
                            'user_uid': api_user['uid']}

            consume_key(user_details,key)
            return JsonResponse({"status": True, "data": bloxy_res})
        except Exception as e:
            print("Exception in CatvOutbound: ", traceback.format_exc())
            return JsonResponse(INTERNAL_SERVER_ERROR, status=500)


class CatvSupportedNetworks(APIView):
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
            res = [{"chain": n, "tokens": (
                True if n not in [c for c in UTXO_CHAINS]+['XRP'] else False)} for n in CATV_SUPPORTED_NETWORKS]
            return JsonResponse({"status": True, "data": res}, status=200)
        except Exception as e:
            print("Exception in CatvSupportedNetworks: ", traceback.format_exc())
            return JsonResponse(INTERNAL_SERVER_ERROR, status=500)


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
            
            data = {"catv_count": auth['catv_count'],"api_calls_left": auth['api_calls_left']}
            return JsonResponse({"status": True, "data": data}, status=200)
        except Exception:
            print(traceback.format_exc())
            return JsonResponse(INTERNAL_SERVER_ERROR, status=500)



class CatvInbound(APIView):
    authentication_classes = []
    permission_classes = []
    def get(self, request, format=None):
        try:
            print("Coming into CatvInbound")
            try:
                key = request.META['HTTP_X_API_KEY']
            except Exception:
                return JsonResponse(API_KEY_MISSING, status=401)
            res = get_user_details(key)
            validated_request = validate_request(request,  key, res, required_params_list=[
                'address', 'chain'], allowed_param_list=['key', 'token', 'from_date', 'till_date', 'depth_limit', 'min_tx_amount', 'limit', 'offset'])
            if isinstance(validated_request, JsonResponse):
                return validated_request
            print("validated_request :", validated_request)
            if not validated_request or validated_request['api_calls_left'] < 1:
                return JsonResponse(INSUFFICIENT_CREDIT, status=402)
            ratelimit_status = validated_request['ratelimit_status']
            if ratelimit_status:
                return JsonResponse({"status": False, "data": {"message": f"Too many requests, your rate limit is {validated_request['rate_limit']}"}}, status=429)
            chain = request.GET.get('chain').upper()
            token = request.GET.get(
                'token', '0x0000000000000000000000000000000000000000')
            if not validate_addr(request.GET.get('address'), chain, token=token, is_catv=True):
                return JsonResponse({"status": False, "data": {"message": f"Invalid address for specified chain"}}, status=400)
            bloxy_res = catv_query('inbound', request, chain)
            if bloxy_res == False:
                return JsonResponse(INTERNAL_SERVER_ERROR, status=500)
            user_data = ast.literal_eval(res)
            api_user = user_data['api_user'][0]
            user_details = {'user_id': user_data['auth']['user_id'],
                            'user_uid': api_user['uid']}

            consume_key(user_details, key)
            return JsonResponse({"status": True, "data": bloxy_res})
        except Exception as e:
            print("Exception in CatvInbound: ", traceback.format_exc())
            return JsonResponse(INTERNAL_SERVER_ERROR, status=500)
