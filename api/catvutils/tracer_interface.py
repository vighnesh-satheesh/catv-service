from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from multiprocessing.pool import ThreadPool
import os
import traceback
from typing import List, Dict, Any, Optional

import requests
from django.conf import settings



class TracerAPIInterface:
    """Interface for Tracer API"""

    def __init__(self):
        self._timeout = (60, 600)

    def get_transactions(
            self,
            address: str,
            tx_limit: int,
            depth,
            depth_limit: int = 2,
            from_time: str = None,
            till_time: str = None,
            token_address: Optional[str] = None,
            source: bool = True,
            chain: str = 'ETH',
            is_ck_request: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get transaction data from Tracer API.
        """
        try:
            # Convert chain to chain_id
            chain_id, chain_type = self._get_chain_info(chain)
            if from_time and 'T' not in from_time:
                start_datetime = f"{from_time}T00:00:00.000Z"
            else:
                start_datetime = from_time

            if not is_ck_request:
                end_datetime = f"{till_time}T23:59:59Z"
            else:
                end_datetime = f"{till_time}Z"

            # Prepare request body
            request_body = {
                "chain_type": chain_type,
                "chain_id": chain_id,
                "start_address": address,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "max_hops": depth_limit,
                "max_workers": 5,
                "tokens": [
                    token_address] if token_address and token_address != "0x0000000000000000000000000000000000000000" else []
            }
            endpoint = 'trace-inbound' if source else "trace-outbound"
            api_url = settings.TRACER_ENDPOINT + endpoint
            print(f"Calling Tracer API: {api_url} body: {json.dumps(request_body)}")
            # Make API call
            response = requests.post(
                api_url,
                json=request_body,
                timeout=self._timeout
            )
            response.raise_for_status()  # Raise exception for HTTP errors
            # Process and return data in the same format as BitqueryAPIInterface
            return self._process_response(response.json(), source, depth, is_ck_request)

        except Exception:
            traceback.print_exc()
            raise

    def _get_chain_info(self, chain: str) -> tuple:
        chain_mapping = {
            'ETH': (1, 'evm'),  # Ethereum Mainnet
            'BSC': (56, 'evm'),  # Binance Smart Chain
            'FTM': (250, 'evm'),  # Fantom
            'POL': (137, 'evm'),  # Polygon
            'ETC': (61, 'evm'),  # Ethereum Classic
            'AVAX': (43114, 'evm'),  # Avalanche
            'TRX': (1, 'tron'),  # Tron
            'BTC': (1, 'btc'),
            'KLAY': (1, 'klaytn'),
            'SOL': (1, 'solana'),
            'XRP': (1, 'xrp'),
            'ARB': (42161, 'evm'),
            'ARBNOVA': (42170, 'evm'),
            'OP': (10, 'evm'),
            'BASE': (8453, 'evm'),
            'LINEA': (59144, 'evm'),
            'BLAST': (81457, 'evm'),
            'SCROLL': (534352, 'evm'),
            'MANTLE': (5000, 'evm'),
            'OPBNB': (204, 'evm'),
            'BTT': (199, 'evm'),
            'CELO': (42220, 'evm'),
            'FRAXTAL': (252, 'evm'),
            'GNOSIS': (100, 'evm'),
            'MEMECORE': (4352, 'evm'),
            'MOONBEAM': (1284, 'evm'),
            'MOONRIVER': (1285, 'evm'),
            'TAIKO': (167000, 'evm'),
            'XDC': (50, 'evm'),
            'APECHAIN': (33139, 'evm'),
            'WORLD': (480, 'evm'),
            'SONIC': (146, 'evm'),
            'UNICHAIN': (130, 'evm'),
            'ABSTRACT': (2741, 'evm'),
            'BERACHAIN': (80094, 'evm'),
            'SWELLCHAIN': (1923, 'evm'),
            'MONAD': (143, 'evm'),
            'HYPEREVM': (999, 'evm'),
            'KATANA': (9745, 'evm'),
            'SEI': (1329, 'evm'),
            'STABLE': (1, 'evm'),
            'PLASMA': (747474, 'evm'),
        }
        return chain_mapping.get(chain, (1, 'evm'))  # Default to Ethereum
    
    def _process_swap(self, swap):
        address = swap["sender"]
        from_time = swap["tx_time"]
        depth = swap["depth"]
        token_address = swap["swap_info"]["token_out"]["address"]
        source = False
        chain: str = 'ETH'
        till_time = datetime.now()
        try:
            print(f"THE TRANSCATION COMING TO swap IS : {swap}")
            swap_node = TracerAPIInterface.create_reverse_swap_transactions(swap)
            print(f"THE TRANSCATION COMING TO swapped_node IS : {swap_node}")
            response = []
            response.append(swap_node)

            results = self.get_transactions(address, 1000, depth, 5, from_time, till_time, token_address, source, chain)
            
            return response + results
        except Exception:
            print("ERROR : process_swap")
            traceback.print_exc()
            return []

    
    def _get_tx_with_swaps(self, initial_data, possible_swaps):
        try:
            print(f"{len(possible_swaps)=}")
            if len(possible_swaps) > 0:
                max_workers = min(32, os.cpu_count() or 4)
                valid_requests = []
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Process results as they complete rather than waiting for all
                    for result in executor.map(self._process_swap, possible_swaps):
                        if result is not None:
                            valid_requests.extend(result)
                
                initial_data.extend(valid_requests)
            return initial_data
        except Exception as e:
            print("ERROR : get_tx_with_swaps")
            traceback.print_exc()
            return None

    def _process_response(self, response_data: Dict, source: bool, depth, is_ck_request: bool = False) -> List[
        Dict[str, Any]]:
        """
        Process the response from Tracer API to match the format expected by TrackingResults.
        """
        transactions = response_data.get('transactions', [])
        swap_transactions = []

        unwanted_fields = [
            'chain_id', 'block_height', 'direction', 'original_value',
            'tracked_value', 'pending_value', 'receiver_sender_type'
            
        ]

        # Process transactions
        for transaction in transactions:
            
            if transaction.get('is_swap') and transaction.get('swap_info'):
                swap_transactions.append(transaction)
            for field in unwanted_fields:
                transaction.pop(field, None)
            transaction['depth'] += depth # adding depth for tracking swapped tokens
            # offsetting depth to -(depth) for source transactions
            if source:
                transaction['depth'] = -transaction['depth']

        # for catv requests bypass processing swap transactions
        if not is_ck_request:
            return transactions

        #return transactions for ck request
        return self._get_tx_with_swaps(transactions, swap_transactions)

    @staticmethod
    def create_reverse_swap_transactions(tx):

        swap_info = tx.get('swap_info', {})
        token_out = swap_info.get('token_out', {})

            # Skip if token_out is missing or invalid
        if not token_out or not isinstance(token_out, dict):
            return

            # Create reverse transaction (from router to original sender)
        reverse_tx = {
            # Keep same identification fields
            "depth": tx.get('depth'),
            "tx_hash": tx.get('tx_hash'),
            "tx_time": tx.get('tx_time'),

            # Swap addresses
            "sender": tx.get('receiver'),  # Router address is now sender
            "receiver": tx.get('sender'),  # Original sender is now receiver

            # Swap annotations and security categories
            "sender_annotation": tx.get('receiver_annotation', ''),
            "receiver_annotation": tx.get('sender_annotation', ''),

            # Token details from token_out
            "token": {
                "address": token_out.get('address', ''),
                "symbol": token_out.get('symbol', ''),
            },
            "token_type": "ERC20",  # Assuming all swap tokens are ERC20
            "token_id": "",

            # Amount from swap_info.amount_out
            "amount": float(swap_info.get('amount_out', 0)),
            "amount_usd": 0,  # Update when value is available

            # Swap sender/receiver types
            "sender_type": tx.get('receiver_type', 'Generic'),
            "receiver_type": tx.get('sender_type', 'Wallet'),
            "is_swap": True
        }

            
        return reverse_tx

    def get_transaction_count(
            self,
            address: str = None,
            tx_hash: str = None,
            chain: str = 'ETH',
            token_contract: str = None,
    ) -> Dict[str, Any]:
        """
        Get transaction count for an address or transaction hash from Tracer API.

        Args:
            address: Wallet address (mutually exclusive with tx_hash)
            tx_hash: Transaction hash (mutually exclusive with address)
            chain: Blockchain identifier
            token_contract: Token contract address
        Returns:
            Dict containing transaction count and metadata
        """
        try:
            chain_id, chain_type = self._get_chain_info(chain)

            if address:
                # Use address endpoint
                endpoint = f"tx-count/{chain_type}/{address}"
                params = {"chain_id": chain_id}
            elif tx_hash:
                # Use transaction hash validation endpoint
                endpoint = f"validate-tx/{chain_type}/{tx_hash}"
                params = {"chain_id": chain_id}
            else:
                raise ValueError("Either address or tx_hash must be provided")

            if token_contract:
                params["contract_address"] = token_contract

            api_url = f"{settings.TRACER_ENDPOINT}{endpoint}"

            print(f"Calling Tracer API: {api_url} with params: {params}")

            response = requests.get(
                api_url,
                params=params,
                timeout=self._timeout
            )
            response.raise_for_status()

            result = response.json()

            # Standardize response format
            if tx_hash and 'transaction_count' in result:
                # Response from validate-tx endpoint
                return {
                    'address': result.get('address'),
                    'chain_type': result.get('chain_type'),
                    'chain_id': result.get('chain_id'),
                    'chain_name': result.get('chain_name'),
                    'transaction_count': result.get('transaction_count', 0)
                }
            else:
                # Response from tx-count endpoint
                return result

        except Exception as e:
            traceback.print_exc()
            raise