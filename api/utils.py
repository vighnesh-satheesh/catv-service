import time
from functools import wraps
import re
from datetime import datetime
import binascii
import base58
import hashlib

from django.db.models import Q
from six import text_type
from django.utils.encoding import force_str

from rest_framework import exceptions as rf_exceptions
from rest_framework.views import exception_handler

from .response import APIResponse
from .models import (
    CatvTokens, CatvHistory, UserRoles
)
from . import exceptions

SUBSCRIBED_ROLES = [UserRoles.INVESTIGATOR_STARTER_CAMS.value, UserRoles.INVESTIGATOR_ADVANCED_CAMS.value,
                        UserRoles.INVESTIGATOR_PRO_CAMS.value]
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
        return text_type(data).lower()

    text = force_str(data)
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

def determine_wallet_type(token_type):
    address_mapping = {
        "ETH": "Ethereum/ERC20",
        "TRX": "Tron",
        "BTC": "Bitcoin",
        "LTC": "Litecoin",
        "BCH": "Bitcoin Cash",
        "XLM": "Stellar",
        "EOS": "EOS",
        "XRP": "Ripple",
        "BNB": "Binance Coin",
        "ADA": "Cardano",
        "BSC": "Binance Smart Chain",
        "KLAY": "Klaytn",
        "LUNC": "LUNC",
        "DOGE": "Doge Coin",
        "ZEC": "Zcash"
    }

    if address_mapping.__contains__(token_type.value):
        return address_mapping[token_type.value]
        
    return "Ethereum/ERC20"


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
        CatvTokens.ADA.value: "^[0-9a-zA-Z]+$",
        CatvTokens.BSC.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.KLAY.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.LUNC.value: "^(terra1)[0-9a-z]{38}$",
        CatvTokens.DOGE.value: "^(D|A|9)[a-km-zA-HJ-NP-Z1-9]{33,34}$",
        CatvTokens.ZEC.value: "^(t)[A-Za-z0-9]{34}$"
    }
    pattern = token_regex_map.get(token_type, None)
    if not pattern:
        return False
    return re.compile(pattern).match(address)

def retry_run(tries=5, delay=15, backoff=2):
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    print("%s, Retrying in %d seconds..." % (str(e), mdelay))
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry

    return deco_retry


def validate_coin(address):

    base58Decoder = base58.b58decode(address).hex()
    prefixAndHash = base58Decoder[:len(base58Decoder)-8]
    checksum = base58Decoder[len(base58Decoder)-8:]

    # to handle true result, we should pass our input to hashlib.sha256() method() as Byte format
    # so we use binascii.unhexlify() method to convert our input from Hex to Byte
    # finally, hexdigest() method convert value to human-readable
    hash = prefixAndHash
    for x in range(1, 3):
        hash = hashlib.sha256(binascii.unhexlify(hash)).hexdigest()

    if(checksum == hash[:8]):
        return True
    else:
        return False


def is_eth_based_wallet(pattern_subtype):
    eth_based_pattern_subtypes = ['ETH', 'BSC', 'KLAY', 'FTM', 'POL', 'ETC', 'AVAX']
    if pattern_subtype in eth_based_pattern_subtypes:
        return True
    return False
