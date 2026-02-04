import binascii
import csv
import hashlib
import random
import re
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import List, Dict, Any

import base58
from django.core.exceptions import SuspiciousOperation
from django.db import connections, close_old_connections, OperationalError
from django.db.utils import InterfaceError
from django.utils.encoding import force_str
from google.cloud import storage
from google.cloud.exceptions import NotFound
from rest_framework import exceptions as rf_exceptions
from rest_framework.views import exception_handler
from six import text_type

from .models import (
    CatvTokens, UserRoles, CatvSearchType
)
from .response import APIResponse
from .serializers import CATVBTCCoinpathSerializer, CatvBtcPathSerializer, CATVSerializer, CATVEthPathSerializer
from .tasks import catv_history_task, catv_path_history_task

SUBSCRIBED_ROLES = [UserRoles.INVESTIGATOR_STARTER_CAMS.value, UserRoles.INVESTIGATOR_ADVANCED_CAMS.value,
                        UserRoles.INVESTIGATOR_PRO_CAMS.value]

serializer_map = {
    CatvTokens.ETH.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.BTC.value: {
        CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
        CatvSearchType.PATH.value: CatvBtcPathSerializer
    },
    CatvTokens.TRON.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.LTC.value: {
        CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
        CatvSearchType.PATH.value: CatvBtcPathSerializer
    },
    CatvTokens.BCH.value: {
        CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
        CatvSearchType.PATH.value: CatvBtcPathSerializer
    },
    CatvTokens.XRP.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.EOS.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.XLM.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.BNB.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.ADA.value: {
        CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
        CatvSearchType.PATH.value: CatvBtcPathSerializer
    },
    CatvTokens.BSC.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.KLAY.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.LUNC.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.FTM.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.POL.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.AVAX.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.DOGE.value: {
        CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
        CatvSearchType.PATH.value: CatvBtcPathSerializer
    },
    CatvTokens.ZEC.value: {
        CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
        CatvSearchType.PATH.value: CatvBtcPathSerializer
    },
    CatvTokens.DASH.value: {
        CatvSearchType.FLOW.value: CATVBTCCoinpathSerializer,
        CatvSearchType.PATH.value: CatvBtcPathSerializer
    },
    CatvTokens.SOL.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.ARB.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.ARBNOVA.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.OP.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.BASE.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.LINEA.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.BLAST.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.SCROLL.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.MANTLE.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.OPBNB.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.BTT.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.CELO.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.FRAXTAL.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.GNOSIS.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.MEMECORE.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.MOONBEAM.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.MOONRIVER.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.TAIKO.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.XDC.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.APECHAIN.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.WORLD.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.SONIC.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.UNICHAIN.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.ABSTRACT.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.BERACHAIN.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.SWELLCHAIN.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.MONAD.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.HYPEREVM.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.KATANA.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.SEI.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.STABLE.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    },
    CatvTokens.PLASMA.value: {
        CatvSearchType.FLOW.value: CATVSerializer,
        CatvSearchType.PATH.value: CATVEthPathSerializer
    }
}

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
        "KLAY": "KAIA",
        "LUNC": "LUNC",
        "FTM": "Fantom",
        "POL": "Polygon",
        "AVAX": "Avalanche",
        "ZEC": "Zcash",
        "DASH": "DASH",
        "DOGE": "Doge Coin",
        "SOL": "Solana",
        "ARB": "Arbitrum",
        "ARBNOVA": "Arbitrum Nova",
        "OP": "Optimism",
        "BASE": "Base",
        "LINEA": "Linea",
        "BLAST": "Blast",
        "SCROLL": "Scroll",
        "MANTLE": "Mantle",
        "OPBNB": "opBNB",
        "BTT": "BitTorrent",
        "CELO": "Celo",
        "FRAXTAL": "Fraxtal",
        "GNOSIS": "Gnosis",
        "MEMECORE": "Memecore",
        "MOONBEAM": "Moonbeam",
        "MOONRIVER": "Moonriver",
        "TAIKO": "Taiko",
        "XDC": "XDC",
        "APECHAIN": "Apechain",
        "WORLD": "World",
        "SONIC": "Sonic",
        "UNICHAIN": "Unichain",
        "ABSTRACT": "Abstract",
        "BERACHAIN": "Berachain",
        "SWELLCHAIN": "Swellchain",
        "MONAD": "Monad",
        "HYPEREVM": "HyperEVM",
        "KATANA": "Katana",
        "SEI": "Sei",
        "STABLE": "Stable",
        "PLASMA": "Plasma"
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
        CatvTokens.FTM.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.POL.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.AVAX.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.DOGE.value: "^(D|A|9)[a-km-zA-HJ-NP-Z1-9]{33,34}$",
        CatvTokens.ZEC.value: "^(t)[A-Za-z0-9]{34}$",
        CatvTokens.DASH.value: "^[X|7][0-9A-Za-z]{33}$",
        CatvTokens.SOL.value: "^[1-9A-HJ-NP-Za-km-z]{32,44}$",
        CatvTokens.ARB.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.ARBNOVA.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.OP.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.BASE.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.LINEA.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.BLAST.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.SCROLL.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.MANTLE.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.OPBNB.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.BTT.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.CELO.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.FRAXTAL.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.GNOSIS.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.MEMECORE.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.MOONBEAM.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.MOONRIVER.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.TAIKO.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.XDC.value: "^(0x|xdc)[a-fA-F0-9]{40}$",
        CatvTokens.APECHAIN.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.WORLD.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.SONIC.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.UNICHAIN.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.ABSTRACT.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.BERACHAIN.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.SWELLCHAIN.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.MONAD.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.HYPEREVM.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.KATANA.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.SEI.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.STABLE.value: "^0x[a-fA-F0-9]{40}$",
        CatvTokens.PLASMA.value: "^0x[a-fA-F0-9]{40}$"
    }
    pattern = token_regex_map.get(token_type, None)
    if not pattern:
        return False
    return re.compile(pattern).match(address)


def validate_labels_csv_file(csv_file):
    """
    Basic validation for uploaded labels CSV file.
    - Ensures presence
    - Checks extension
    - Checks max size (1MB)
    """
    if not csv_file:
        raise ValueError("CSV file is required")

    if not getattr(csv_file, "name", "").endswith(".csv"):
        raise ValueError("Invalid file type. Please upload a CSV file.")

    # Basic size guard: 1MB like frontend
    if getattr(csv_file, "size", 0) > 1024 * 1024:
        raise ValueError("File too large. Please upload a file smaller than 1MB.")

    return True


def find_main_token_symbol(item_list):
    """
    Determine the main token symbol from item_list.
    
    Uses a sample of up to 20 transactions to determine the most frequent symbol.
    
    Raises:
        ValueError: If item_list is empty or no symbol can be determined.
    """
    if not item_list:
        raise ValueError("Cannot determine chain type: item_list is empty")
    
    # Use a sample of up to 20 transactions to determine main token
    sample_size = min(20, len(item_list))
    sample_items = item_list[:sample_size]
    
    # Count occurrences of each token symbol
    token_counts = {}
    for item in sample_items:
        symbol = item.get('symbol')
        if symbol:
            token_counts[symbol] = token_counts.get(symbol, 0) + 1
    
    # Find the symbol with highest count
    if token_counts:
        return max(token_counts.items(), key=lambda x: x[1])[0]
    else:
        raise ValueError("Cannot determine chain type: no token symbols found in item_list")


def calculate_wallet_total_amount(
    item_list: List[Dict[str, Any]],
    wallet_address: str,
    main_symbol: str,
    depth: int,
) -> float:
    """
    Calculate total_amount for a wallet using logic from _calculate_wallet_metrics.
    
    This is the same logic used in CATVNodeLabelView._calculate_wallet_total_amount
    to ensure consistency across the codebase.
    
    Args:
        item_list: List of transaction items from report
        wallet_address: Wallet address to calculate for
        main_symbol: Main token symbol (e.g., 'ETH', 'BTC')
        depth: Depth/level of the wallet in the graph
        
    Returns:
        Total amount for the wallet
    """
    if not wallet_address or not main_symbol or not isinstance(item_list, list):
        return 0.0
    
    # Determine if it's distribution (depth > 0) or source (depth < 0)
    is_outbound = depth > 0 if depth is not None else True
    is_btc_ltc = main_symbol in ["BTC", "LTC"]
    
    # Filter for main token transactions (excluding swaps)
    main_token_items = [
        item for item in item_list
        if item.get('symbol') == main_symbol and not item.get('is_swap', False)
    ]
    
    wallet_amount = 0.0
    
    if is_btc_ltc and is_outbound:
        # Special logic for BTC/LTC distribution side
        addresses_with_outgoing = set()
        for item in main_token_items:
            addresses_with_outgoing.add(item.get('sender', '').lower())
        
        all_receivers = set()
        for item in main_token_items:
            all_receivers.add(item.get('receiver', '').lower())
        
        wallet_lower = wallet_address.lower()
        processed_txs = set()
        processed_leaf_txs = set()
        
        # Check if wallet is a non-leaf node (has outgoing transactions)
        if wallet_lower in addresses_with_outgoing and wallet_lower in all_receivers:
            # Process non-leaf node: sum from_amount where wallet is sender
            for item in main_token_items:
                sender = item.get('sender', '').lower()
                tx_hash = item.get('tx_hash')
                
                if sender == wallet_lower and tx_hash and tx_hash not in processed_txs:
                    amount = item.get('from_amount', item.get('amount', 0))
                    wallet_amount += abs(float(amount))
                    processed_txs.add(tx_hash)
        
        # Check if wallet is a leaf node (no outgoing transactions)
        if wallet_lower not in addresses_with_outgoing:
            # Process leaf node: sum to_amount where wallet is receiver
            for item in main_token_items:
                receiver = item.get('receiver', '').lower()
                tx_hash = item.get('tx_hash')
                
                if receiver == wallet_lower and tx_hash and tx_hash not in processed_leaf_txs:
                    amount = item.get('to_amount', item.get('amount', 0))
                    wallet_amount += abs(float(amount))
                    processed_leaf_txs.add(tx_hash)
    else:
        # Original logic for non-BTC/LTC or source side
        wallet_lower = wallet_address.lower()
        for item in main_token_items:
            if is_outbound:
                # Distribution: sum amounts where wallet is receiver
                receiver = item.get('receiver', '').lower()
                if receiver == wallet_lower:
                    wallet_amount += abs(float(item.get('amount', 0)))
            else:
                # Source: sum amounts where wallet is sender
                sender = item.get('sender', '').lower()
                if sender == wallet_lower:
                    wallet_amount += abs(float(item.get('amount', 0)))
    
    return wallet_amount


def calculate_wallets_total_amounts(
    item_list: List[Dict[str, Any]],
    wallets: List[Dict[str, Any]],
    main_symbol: str,
) -> Dict[str, float]:
    """
    Calculate total_amount for multiple wallets efficiently.
    
    Optimized version using pre-indexed dictionaries for O(1) lookups
    instead of O(n) iterations per wallet.
    
    Args:
        item_list: List of transaction items from report
        wallets: List of wallet dicts with at least 'address' and 'depth' keys
        main_symbol: Main token symbol (e.g., 'ETH', 'BTC')
        
    Returns:
        Dictionary mapping wallet_address (lowercase) to total_amount
    """
    if not wallets or not item_list or not main_symbol:
        return {}
    
    # Pre-filter main token items once for all wallets
    main_token_items = [
        item for item in item_list
        if item.get('symbol') == main_symbol and not item.get('is_swap', False)
    ]
    
    if not main_token_items:
        return {wallet.get('address', '').lower(): 0.0 for wallet in wallets if wallet.get('address')}
    
    is_btc_ltc = main_symbol in ["BTC", "LTC"]
    
    # Pre-compute sets and indexes for faster lookups
    addresses_with_outgoing = set()
    all_receivers = set()
    
    # Index items by sender/receiver for O(1) lookups
    items_by_sender = {}  # sender_lower -> list of items
    items_by_receiver = {}  # receiver_lower -> list of items
    
    for item in main_token_items:
        sender = (item.get('sender') or '').lower()
        receiver = (item.get('receiver') or '').lower()
        
        if is_btc_ltc:
            addresses_with_outgoing.add(sender)
            all_receivers.add(receiver)
        
        # Index by sender
        if sender:
            if sender not in items_by_sender:
                items_by_sender[sender] = []
            items_by_sender[sender].append(item)
        
        # Index by receiver
        if receiver:
            if receiver not in items_by_receiver:
                items_by_receiver[receiver] = []
            items_by_receiver[receiver].append(item)
    
    results = {}
    
    for wallet in wallets:
        wallet_address = wallet.get('address', '').strip()
        if not wallet_address:
            continue
        
        depth = wallet.get('depth')
        if depth is None:
            depth = wallet.get('level', 0)
        
        is_outbound = depth > 0 if depth is not None else True
        wallet_lower = wallet_address.lower()
        
        wallet_amount = 0.0
        
        if is_btc_ltc and is_outbound:
            processed_txs = set()
            processed_leaf_txs = set()
            
            # Check if wallet is a non-leaf node
            if wallet_lower in addresses_with_outgoing and wallet_lower in all_receivers:
                # Use indexed items instead of iterating all items
                for item in items_by_sender.get(wallet_lower, []):
                    tx_hash = item.get('tx_hash')
                    if tx_hash and tx_hash not in processed_txs:
                        amount = item.get('from_amount', item.get('amount', 0))
                        wallet_amount += abs(float(amount))
                        processed_txs.add(tx_hash)
            
            # Check if wallet is a leaf node
            if wallet_lower not in addresses_with_outgoing:
                # Use indexed items instead of iterating all items
                for item in items_by_receiver.get(wallet_lower, []):
                    tx_hash = item.get('tx_hash')
                    if tx_hash and tx_hash not in processed_leaf_txs:
                        amount = item.get('to_amount', item.get('amount', 0))
                        wallet_amount += abs(float(amount))
                        processed_leaf_txs.add(tx_hash)
        else:
            # Original logic for non-BTC/LTC or source side - use indexed lookups
            if is_outbound:
                # Distribution: sum amounts where wallet is receiver
                for item in items_by_receiver.get(wallet_lower, []):
                    wallet_amount += abs(float(item.get('amount', 0)))
            else:
                # Source: sum amounts where wallet is sender
                for item in items_by_sender.get(wallet_lower, []):
                    wallet_amount += abs(float(item.get('amount', 0)))
        
        results[wallet_lower] = wallet_amount
    
    return results


def match_report_labels_from_csv(
    csv_content: str,
    node_list: List[Dict[str, Any]],
    item_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Match CSV wallet_address,label against node_list and calculate per-wallet totals.

    Uses find_main_token_symbol to determine the main token, then calculates
    totals using the same logic as CATVNodeLabelView.

    Raises:
        ValueError: If chain type cannot be determined from item_list.

    Returns dict with:
      - node_list (updated with label/group)
      - wallets (list of {address, total_amount, depth, id, label})
      - total_amount (sum of totals)
      - updated_count
    """
    if not csv_content:
        return {
            "node_list": node_list,
            "wallets": [],
            "total_amount": 0.0,
            "updated_count": 0,
        }

    reader = csv.DictReader(csv_content.splitlines())
    required_fields = ["wallet_address", "label"]
    if not reader.fieldnames or not all(field in reader.fieldnames for field in required_fields):
        raise ValueError("CSV must contain 'wallet_address' and 'label' columns.")

    # Determine main token symbol - raises ValueError if cannot be determined
    main_symbol = find_main_token_symbol(item_list)

    # Build node lookup by address
    node_dict = {
        (node.get("address") or "").lower(): node
        for node in node_list
        if node.get("address")
    }

    # First pass: collect all matched wallets with their info
    matched_wallets_info: List[Dict[str, Any]] = []
    updated_count = 0

    for row in reader:
        wallet_address_raw = (row.get("wallet_address") or "").strip()
        label = (row.get("label") or "").strip()
        if not wallet_address_raw:
            continue

        wallet_address = wallet_address_raw.lower()
        node = node_dict.get(wallet_address)
        if not node:
            continue

        # Update node with user label info
        node["label"] = label
        node["group"] = "User Label"
        updated_count += 1

        # Determine depth/level
        depth = node.get("depth")
        if depth is None:
            depth = node.get("level", 0)
        print("Updated")
        matched_wallets_info.append({
            "address": wallet_address_raw,
            "depth": depth,
            "id": node.get("id", 0),
            "label": label,
        })

    # Calculate totals for all wallets at once (more efficient)
    if matched_wallets_info:
        totals_dict = calculate_wallets_total_amounts(
            item_list=item_list,
            wallets=matched_wallets_info,
            main_symbol=main_symbol,
        )

        # Add total_amount to each wallet
        for wallet in matched_wallets_info:
            wallet_lower = wallet["address"].lower()
            wallet["total_amount"] = totals_dict.get(wallet_lower, 0.0)
    else:
        # No matches, return empty result
        for wallet in matched_wallets_info:
            wallet["total_amount"] = 0.0

    total_amount_sum = sum(w.get("total_amount", 0.0) for w in matched_wallets_info)

    return {
        "node_list": node_list,
        "wallets": matched_wallets_info,
        "total_amount": total_amount_sum,
        "updated_count": updated_count,
    }

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
    eth_based_pattern_subtypes = [
        'ETH', 'BSC', 'KLAY', 'FTM', 'POL', 'ETC', 'AVAX',
        'ARB', 'ARBNOVA', 'OP', 'BASE', 'LINEA', 'BLAST', 'SCROLL',
        'MANTLE', 'OPBNB', 'BTT', 'CELO', 'FRAXTAL', 'GNOSIS', 'MEMECORE',
        'MOONBEAM', 'MOONRIVER', 'TAIKO', 'XDC', 'APECHAIN', 'WORLD', 'SONIC',
        'UNICHAIN', 'ABSTRACT', 'BERACHAIN', 'SWELLCHAIN', 'MONAD', 'HYPEREVM',
        'KATANA', 'SEI', 'STABLE', 'PLASMA'
    ]
    if pattern_subtype in eth_based_pattern_subtypes:
        return True
    return False

def get_gcs_file(bucket_name, filename):
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    try:
        blob = bucket.blob(filename)
        content = blob.download_as_text()  # Use download_as_bytes() for binary content
        return content
    except NotFound:
        raise SuspiciousOperation(f"The file '{filename}' does not exist in the GCS bucket.")


def ensure_db_connections(*db_aliases):
    def decorator(func):
        @wraps(func)
        def inner(*args, **kwargs):
            retries = 0
            max_retries = 3
            retry_delay = 5
            while retries < max_retries:
                try:
                    for db_alias in db_aliases:
                        print(f"ensuring connection for {db_alias} before rpc")
                        connections[db_alias].ensure_connection()
                    return func(*args, **kwargs)
                except (OperationalError, InterfaceError) as e:
                    print(f"Database connection error: {e}, retrying...")
                    close_old_connections()
                    time.sleep(retry_delay)
                    retries += 1
                except Exception as e:
                    print(f"Unexpected error: {e}")
                    close_old_connections()
                    time.sleep(retry_delay)
                    retries += 1
            return None
        return inner
    return decorator


def retry_on_db_error(*db_aliases, max_retries=3, retry_delay=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while attempt < max_retries:
                try:
                    return func(*args, **kwargs)
                except (InterfaceError, OperationalError) as e:
                    try:
                        for db_alias in db_aliases:
                            print("Closing db_alias connection")
                            connections[db_alias].close()
                    except Exception:
                        pass
                    attempt += 1
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                    else:
                        raise
        return wrapper
    return decorator

utils_map = {
    CatvSearchType.FLOW.value: {
        'pattern_creator': create_tracking_cache_pattern,
        'history_runner': catv_history_task
    },
    CatvSearchType.PATH.value: {
        'pattern_creator': create_path_cache_pattern,
        'history_runner': catv_path_history_task
    }
}


def validate_dateformat_and_randomize_seconds(value, output_format):
    random_seconds = random.randint(1, 59)
    try:
        date_obj = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        try:
            date_obj = datetime.strptime(value, '%Y-%m-%d')
            date_obj = date_obj.replace(hour=0, minute=0, second=0)
        except ValueError:
            raise ValueError(f"Time data '{value}' does not match format '%Y-%m-%d %H:%M:%S' or '%Y-%m-%d'")
    date_obj += timedelta(seconds=random_seconds)
    return date_obj.strftime(output_format)


def extract_error_type(message):
    if "ActiveRecord::ActiveRecordError" in message:
        return "MemoryLimitExceeded"
    elif "Net::ReadTimeout" in message:
        return "ReadTimeout"
    elif "It is not possible to execute 2 simultaneous requests" in message:
        return "ConcurrencyLimitExceeded"
    elif "Bitquery request timed out" in message:
        return  "BitqueryRequestTimedOut"
    elif "Ck Transactions limit exceeded" in message:
        return "CkTransactionsLimitExceeded"
    else:
        return "UnknownError"


def build_error_response(bitquery_res):
    # Extract the error details from the first item in the list
    error_details = bitquery_res['errors'][0]

    error_type = extract_error_type(error_details['message'])
    # Build the standardized error response
    standardized_error = {
        "error": {
            "type": error_type,
            "message": error_details['message'],
            "query_id": error_details.get('query_id', ''),
            "path": error_details.get('path', [])
        }
    }

    return standardized_error

def get_bool_param(params, key, default=False):
    value = params.pop(key, default)
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        value = value.lower()
        if value == "true":
            return True
        elif value == "false":
            return False

    return default
