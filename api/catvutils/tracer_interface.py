import json
import traceback
from typing import List, Dict, Any, Optional

import requests
from django.conf import settings



class TracerAPIInterface:
    """Interface for Tracer API"""

    def __init__(self):
        self._api_url = settings.TRACER_ENDPOINT
        self._timeout = (60, 600)

    def get_transactions(
            self,
            address: str,
            tx_limit: int,
            depth_limit: int = 2,
            from_time: str = None,
            till_time: str = None,
            token_address: Optional[str] = None,
            source: bool = True,
            chain: str = 'ETH'
    ) -> List[Dict[str, Any]]:
        """
        Get transaction data from Tracer API.
        """
        try:
            # Convert chain to chain_id
            chain_id = self._get_chain_id(chain)
            if from_time and 'T' not in from_time:
                start_datetime = f"{from_time}T00:00:00.000Z"
            else:
                start_datetime = from_time

            end_datetime = f"{till_time}Z"
            # Prepare request body
            request_body = {
                "chain_type": "evm",
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
            self._api_url += endpoint
            print(f"Calling Tracer API: {self._api_url} body: {json.dumps(request_body)}")
            # Make API call
            response = requests.post(
                self._api_url,
                json=request_body,
                timeout=self._timeout
            )
            response.raise_for_status()  # Raise exception for HTTP errors
            # Process and return data in the same format as BitqueryAPIInterface
            return self._process_response(response.json(), source)

        except Exception:
            traceback.print_exc()
            raise

    def _get_chain_id(self, chain: str) -> int:
        """
        Convert chain name to chain_id.
        """
        chain_mapping = {
            'ETH': 1,  # Ethereum Mainnet
            'BSC': 56,  # Binance Smart Chain
            'FTM': 250,  # Fantom
            'POL': 137,  # Polygon
            'ETC': 61,  # Ethereum Classic
            'AVAX': 43114,  # Avalanche
            'KLAY': 8217,  # Klaytn (not used by Tracer but included for completeness)
            # Add other chains as needed
        }
        return chain_mapping.get(chain, 1)  # Default to Ethereum

    def _process_response(self, response_data: Dict, source: bool) -> List[Dict[str, Any]]:
        """
        Process the response from Tracer API to match the format expected by TrackingResults.
        """
        transactions = response_data.get('transactions', [])

        unwanted_fields = [
            'chain_id', 'block_height', 'direction', 'original_value',
            'tracked_value', 'pending_value', 'receiver_sender_type',
            'sender_security_category', 'receiver_security_category'
        ]

        # Process transactions
        for transaction in transactions:
            # Remove unwanted fields
            for field in unwanted_fields:
                transaction.pop(field, None)

            # offsetting depth to -(depth) for source transactions
            if source:
                transaction['depth'] = -transaction['depth']

        # Process swaps to create reverse transactions
        swap_transactions = [tx for tx in transactions if tx.get('is_swap') and tx.get('swap_info')]
        reverse_swap_transactions = TracerAPIInterface.create_reverse_swap_transactions(swap_transactions)

        # Add the reverse swap transactions to the original list
        if reverse_swap_transactions:
            transactions.extend(reverse_swap_transactions)
            print(f"Added {len(reverse_swap_transactions)} reverse swap transactions")

        return transactions

    @staticmethod
    def create_reverse_swap_transactions(swap_transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create reverse transactions for swaps to visualize token flow from router back to sender.

        Args:
            swap_transactions: List of transactions with is_swap=true and valid swap_info

        Returns:
            List of new transaction objects representing the reverse swap flow
        """
        reverse_transactions = []

        for tx in swap_transactions:
            swap_info = tx.get('swap_info', {})
            token_out = swap_info.get('token_out', {})

            # Skip if token_out is missing or invalid
            if not token_out or not isinstance(token_out, dict):
                continue

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
                "symbol": token_out.get('symbol', ''),
                "token": token_out.get('address', ''),
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

            reverse_transactions.append(reverse_tx)

        return reverse_transactions
