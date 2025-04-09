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
            return self._process_response(response.json(), source, depth)

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
            'BTC': (1, 'btc')
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


    def _process_response(self, response_data: Dict, source: bool, depth) -> List[Dict[str, Any]]:
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

        #return transactions
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
