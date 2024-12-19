import traceback
import requests
from multiprocessing.pool import ThreadPool
from requests.exceptions import Timeout, RequestException

from api.constants import Constants
from api.settings import api_settings
from api import utils

def safe_get(dict_obj, *keys, default=None):
    """Safely get nested dictionary values"""
    try:
        result = dict_obj
        for key in keys:
            if not isinstance(result, dict):
                return default
            result = result.get(key)
            if result in [None, "None"]:
                return default
        return result
    except Exception:
        return default

class GraphQLInterface:

    def __init__(self, chain, source, depth_limit, till_time, limit, is_ck_request=False):
        self._graphql_key = api_settings.GRAPHQL_X_API_KEY
        self._graphql_endpoint = api_settings.GRAPHQL_ENDPOINT
        self._headers = {'X-API-KEY': self._graphql_key}
        self.chain = chain
        self.source = source
        self.depth = depth_limit
        self.till_time = str(till_time).replace(" ", "T")
        self.limit = int(limit)
        self.connect_timeout = 60
        self.read_timeout = 300
        self.is_ck_request = is_ck_request

    def _get_template_and_params(self, address: str, token_address: str, from_time: str) -> tuple:
        """Determine which template to use and prepare its parameters"""
        template_key = Constants.CHAIN_TEMPLATE_MAPPING[self.chain]

        if self.is_ck_request:
            template = Constants.CATV_QUERY_TEMPLATES[template_key]
        else:
            template = Constants.CATV_QUERY_TEMPLATES[template_key]


        params = {
            'network': f"{Constants.NETWORK_CHAIN_MAPPING_FOR_RESPONSE[self.chain]} (network: {Constants.NETWORK_CHAIN_MAPPING_FOR_QUERY[self.chain]})",
            'direction': "inbound" if self.source else "outbound",
            'address': address,
            'depth': self.depth,
            'from_time': from_time,
            'till_time': self.till_time,
            'limit': self.limit,
            'currency': "",
            'tags': ""
        }

        # Handle currency parameter for token-supporting chains
        if template_key in ["ETHEREUM_LIKE", "BINANCE_TRON"]:
            if token_address and token_address != '0x0000000000000000000000000000000000000000':
                params['currency'] = f'currency: {{ is: "{token_address}" }}'
            elif self.chain not in ["FTM", "POL", "AVAX"]:  # Only set default currency for specific chains
                currency_value = Constants.GRAPHQL_CURRENCY_MAPPING.get(self.chain)
                params['currency'] = f'currency: {{ is: "{currency_value}" }}' if currency_value else ""
            # Handle special tags for XRP
        elif template_key == "RIPPLE_STELLAR":
            params['tags'] = "destinationTag sourceTag" if self.chain == "XRP" else ""

        return template, params

    def _graphql_query_builder(self, address: str, token_address: str, from_time: str) -> str:
        """Build GraphQL query using templates"""
        try:
            from_time = utils.validate_dateformat_and_randomize_seconds(from_time, "%Y-%m-%dT%H:%M:%S")
            from_time = str(from_time).replace(" ", "T")

            template, params = self._get_template_and_params(address, token_address, from_time)
            return template.safe_substitute(params)
        except Exception:
            traceback.print_exc()
            return None

    def _graphql_dex_trades_query_builder(self, tx_hash):

        network = Constants.NETWORK_CHAIN_MAPPING_FOR_RESPONSE[self.chain] + \
                  " (network: " + Constants.NETWORK_CHAIN_MAPPING_FOR_QUERY[self.chain] + " ) "

        try:
            GRAPHQL_DEX_QUERY = f"""
                query sentinel_query {{
                    {network} {{
                        dexTrades(
                        txHash: {{ is: "{tx_hash}" }}
                        ) {{
                            block {{
                                timestamp {{
                                time(format: "%Y-%m-%d %H:%M:%S")
                                }}
                                height
                            }}
                            tradeIndex
                            protocol
                            exchange {{
                                fullName
                            }}
                            smartContract {{
                                address {{
                                address
                                annotation
                                }}
                            }}
                            buyAmount
                            buy_amount_usd: buyAmount(in: USD)
                            buyCurrency {{
                                address
                                symbol
                            }}
                            sellAmount
                            sell_amount_usd: sellAmount(in: USD)
                            sellCurrency {{
                                address
                                name
                                symbol
                            }}
                        }}
                    }}
                }}   
                """
            return GRAPHQL_DEX_QUERY
        except Exception as e:
            traceback.print_exc()
            return None

    def modify_swap_data(self, swap, new_amount=0, new_amount_usd=0, new_currency=None):

        def deep_copy_safe(obj):
            if isinstance(obj, dict):
                return {k: deep_copy_safe(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [deep_copy_safe(x) for x in obj]
            else:
                return obj

        def update_amount_fields(obj, new_val):
            if isinstance(obj, dict):
                for key in obj:
                    if isinstance(obj[key], (dict, list)):
                        update_amount_fields(obj[key], new_val)
                    elif key in ['amount', 'value', 'txValue']:
                        obj[key] = float(new_val)
                    elif key in ['amountOut', 'amountIn']:
                        obj[key] = str(new_val)

        try:

            modified_swap = deep_copy_safe(swap)

            original_sender = deep_copy_safe(swap.get('sender', {}))
            original_receiver = deep_copy_safe(swap.get('receiver', {}))

            modified_swap['sender'] = {
                'address': original_receiver.get('address', ''),
                'annotation': original_receiver.get('annotation'),
                'type': original_receiver.get('type', 'Wallet'),
                'receiversCount': original_receiver.get('receiversCount'),
                'sendersCount': original_receiver.get('sendersCount'),
                'amountOut': str(new_amount),
                'amountIn': str(new_amount),
                'balance': original_receiver.get('balance', '0.0'),
                'firstTxAt': original_receiver.get('firstTxAt'),
                'lastTxAt': original_receiver.get('lastTxAt'),
                'smartContract': original_receiver.get('smartContract')
            }

            modified_swap['receiver'] = {
                'address': original_sender.get('address', ''),
                'annotation': original_sender.get('annotation'),
                'type': original_sender.get('type', 'Wallet'),
                'receiversCount': original_sender.get('receiversCount'),
                'sendersCount': original_sender.get('sendersCount'),
                'amountOut': str(new_amount),
                'amountIn': str(new_amount),
                'balance': original_sender.get('balance', '0.0'),
                'firstTxAt': original_sender.get('firstTxAt'),
                'lastTxAt': original_sender.get('lastTxAt'),
                'smartContract': original_sender.get('smartContract')
            }

            update_amount_fields(modified_swap, new_amount)

            if 'amount_usd' in modified_swap:
                modified_swap['amount_usd'] = new_amount_usd

            default_currency = {
                'name': '',
                'symbol': '',
                'tokenId': '',
                'tokenType': '',
                'address': ''
            }

            if new_currency and isinstance(new_currency, dict):
                modified_swap['currency'] = {**default_currency, **new_currency}
            else:
                modified_swap['currency'] = default_currency

            if 'transaction' in modified_swap:
                modified_swap['transaction']['value'] = new_amount

            if 'transactions' in modified_swap:
                for tx in modified_swap['transactions']:
                    tx['txValue'] = new_amount
                    tx['amount'] = new_amount

            return modified_swap

        except Exception as e:
            print(f"Error modifying swap data: {str(e)}")
            return None

    def process_swap(self, swap):
        tx_hash = swap["transaction"]["hash"]
        initial_depth = swap["depth"] - 1  # to adjust for the depth issue
        sender = swap["sender"]["address"]
        request_body = self._graphql_dex_trades_query_builder(tx_hash)
        print(f"THE TRANSCATION COMING TO SWAP IS : {swap}")
        if request_body is None or len(request_body) == 0:
            return []

        try:
            r = requests.post(self._graphql_endpoint, json={'query': request_body}, headers=self._headers,
                              timeout=(self.connect_timeout, self.read_timeout))
            response_object = r.json()
            dex_trades = response_object["data"][Constants.NETWORK_CHAIN_MAPPING_FOR_RESPONSE[self.chain]]["dexTrades"]
            if len(dex_trades) < 1:
                return None
            initial_smartcontract_address = dex_trades[0]['smartContract']['address']['address']
            if initial_smartcontract_address != swap["receiver"]["address"]:
                return None
            final_currency_address = dex_trades[-1]['sellCurrency']['address']
            from_time = dex_trades[-1]['block']['timestamp']['time']
            new_amount = dex_trades[-1]['sellAmount']
            new_amount_usd = dex_trades[-1]['sell_amount_usd']

            token_address = dex_trades[-1]['sellCurrency']['address']

            new_currency = {"name": dex_trades[-1]['sellCurrency']['name'],
                            "symbol": dex_trades[-1]['sellCurrency']['symbol'],
                            "address": token_address
                            }
            swap_node = self.modify_swap_data(swap, new_amount, new_amount_usd, new_currency)

            print(f"THE TRANSCATION COMING TO swap_node IS : {swap_node}")

            response = []

            self.flatten_node(0, swap_node, response, [], token_address)

            results = self.call_graphql_endpoint(sender, final_currency_address, from_time, initial_depth)
            return response + results
        except Exception:
            print("ERROR : process_swap")
            traceback.print_exc()
            return []

    def get_tx_with_swaps(self, initial_data, possible_swaps):

        try:

            if len(possible_swaps) > 0:
                with ThreadPool(processes=len(possible_swaps)) as pool:
                    results = pool.map(self.process_swap, possible_swaps)

                valid_requests = [item for result in results if result is not None for item in result]
                initial_data.extend(valid_requests)

            return initial_data

        except Exception as e:
            print("ERROR : get_tx_with_swaps")
            traceback.print_exc()
            return None

    def is_swaps(self, item):
        try:

            dex_keywords = [
                'dex', 'swap', 'exchange', 'uniswap', 'sushiswap',
                'pancakeswap'
            ]

            receiver = item.get('receiver', {})
            annotation = receiver.get('annotation', '').lower() if receiver.get('annotation') else ''
            contract_type = (
                receiver.get('smartContract', {}).get('contractType', '') if receiver.get('smartContract') else '')

            if contract_type:
                for keyword in dex_keywords:
                    if keyword in annotation or keyword in contract_type.lower():
                        return True

            return False
        except Exception:
            print("ERROR : is_swaps")
            traceback.print_exc()
            return False

    # def flatten_node(self, initial_depth, item, flattened_response, possible_swaps, token_address):
    #
    #     depth = int(item["depth"]) + initial_depth
    #
    #     current_iter_dict = {
    #         "depth": depth,
    #         "tx_hash": item["transaction"]["hash"],
    #         "sender": item["sender"]["address"],
    #         "receiver": item["receiver"]["address"],
    #         "sender_annotation": item["sender"]["annotation"] if item["sender"]["annotation"] not in [None,
    #                                                                                                   "None"] else "",
    #         "receiver_annotation": item["receiver"]["annotation"] if item["receiver"]["annotation"] not in [
    #             None, "None"] else ""
    #     }
    #     # XRP and XLM have the same parameters so they are grouped together
    #     if self.chain in ["XRP", "XLM"]:
    #         current_iter_dict["tx_time"] = item["transaction"]["time"]["time"]
    #         current_iter_dict["sent_amount"] = item["amountFrom"]
    #         current_iter_dict["sent_tx_value"] = item["transaction"]["valueFrom"]
    #         current_iter_dict["sent_currency"] = item["currencyFrom"]["symbol"]
    #         current_iter_dict["received_amount"] = item["amountTo"]
    #         current_iter_dict["received_tx_value"] = item["transaction"]["valueTo"]
    #         current_iter_dict["received_currency"] = item["currencyTo"]["symbol"]
    #         current_iter_dict["operation_type"] = item["operation"]
    #         current_iter_dict["receiver_receive_from_count"] = item["receiver"]["receiversCount"]
    #         current_iter_dict["receiver_send_to_count"] = item["receiver"]["sendersCount"]
    #         current_iter_dict["receiver_first_transfer_at"] = item["receiver"]["firstTransferAt"]["time"] if \
    #         item["receiver"]["firstTransferAt"] not in [
    #             None, "None"] else None
    #         current_iter_dict["receiver_last_transfer_at"] = item["receiver"]["lastTransferAt"]["time"] if \
    #         item["receiver"]["lastTransferAt"] not in [
    #             None, "None"] else None
    #         if self.chain == "XRP" and item.get("destinationTag"):
    #             current_iter_dict["destination_tag"] = item["destinationTag"]
    #         if self.chain == "XRP" and item.get("sourceTag"):
    #             current_iter_dict["source_tag"] = item["sourceTag"]
    #         flattened_response.append(current_iter_dict)
    #         return
    #     else:
    #         # The symbol and amount/amount_usd parameters are common to all except XRP and XLM, they are assigned here itself
    #         current_iter_dict["symbol"] = item["currency"]["symbol"]
    #         current_iter_dict["amount"] = item["amount"]
    #         current_iter_dict["amount_usd"] = item["amount_usd"]
    #         if self.chain == "LUNC":
    #             current_iter_dict["tx_time"] = item["block"]["timestamp"]["time"]
    #             current_iter_dict["tx_value"] = item["transaction"]["value"]
    #             flattened_response.append(current_iter_dict)
    #             return
    #         else:
    #             # BCH, LTC, DOGE, ZEC, DASH and ADA have almost all parameters in common
    #             # except sender_type and receiver_type
    #             if self.chain in ["BTC", "BCH", "LTC", "ADA", "DOGE", "ZEC", "DASH"]:
    #                 if self.chain in ["BTC", "DOGE", "DASH"]:
    #                     if item["receiver"]["type"] == "coinbase" and item["receiver"]["address"] == "":
    #                         return
    #                 current_iter_dict["tx_time"] = item["transactions"][0]["timestamp"]
    #                 current_iter_dict["tx_value_in"] = item["transaction"]["valueIn"]
    #                 current_iter_dict["tx_value_out"] = item["transaction"]["valueOut"]
    #                 if self.chain in ["BTC", "BCH", "LTC", "DOGE", "ZEC", "DASH"]:
    #                     current_iter_dict["sender_type"] = item["sender"]["type"]
    #                     current_iter_dict["receiver_type"] = item["receiver"]["type"]
    #                     if self.chain == "ZEC":
    #                         if current_iter_dict["sender"] == "" and current_iter_dict["sender_type"]:
    #                             current_iter_dict["sender"] = current_iter_dict["sender_type"]
    #                         if current_iter_dict["sender"] == "<shielded>" and current_iter_dict[
    #                             "sender_type"] == "shielded":
    #                             current_iter_dict["sender"] = "shielded"
    #                         if current_iter_dict["receiver"] == "" and current_iter_dict["receiver_type"]:
    #                             current_iter_dict["receiver"] = current_iter_dict["receiver_type"]
    #                         if current_iter_dict["receiver"] == "<shielded>" and current_iter_dict[
    #                             "receiver_type"] == "shielded":
    #                             current_iter_dict["receiver"] = "shielded"
    #                     flattened_response.append(current_iter_dict)
    #                     return
    #                 elif self.chain == "ADA":
    #                     current_iter_dict["sender_type"] = "unknown"
    #                     current_iter_dict["receiver_type"] = "unknown"
    #                     flattened_response.append(current_iter_dict)
    #                     return
    #             else:
    #                 # the parameters below are common to all the following blockchains
    #                 current_iter_dict["token_id"] = item["currency"]["tokenId"]
    #                 current_iter_dict["token_type"] = item["currency"]["tokenType"]
    #                 current_iter_dict["receiver_receivers_count"] = item["receiver"]["receiversCount"]
    #                 current_iter_dict["receiver_senders_count"] = item["receiver"]["sendersCount"]
    #                 current_iter_dict["receiver_first_tx_at"] = item["receiver"]["firstTxAt"]["time"] if \
    #                 item["receiver"]["firstTxAt"] not in [
    #                     None, "None"] else None
    #                 current_iter_dict["receiver_last_tx_at"] = item["receiver"]["lastTxAt"]["time"] if item["receiver"][
    #                                                                                                        "lastTxAt"] not in [
    #                                                                                                        None,
    #                                                                                                        "None"] else None
    #                 current_iter_dict["receiver_amount_out"] = float(item["receiver"]["amountOut"])
    #                 current_iter_dict["receiver_amount_in"] = float(item["receiver"]["amountIn"])
    #                 current_iter_dict["receiver_balance"] = float(item["receiver"]["balance"])
    #                 if self.chain in ["ETH", "KLAY", "BSC", "FTM", "POL", "AVAX"]:
    #                     current_iter_dict["token"] = token_address
    #                     current_iter_dict["tx_time"] = item["transactions"][0]["timestamp"]
    #                     current_iter_dict["sender_type"] = item["sender"]["smartContract"]["contractType"] if \
    #                         item["sender"]["smartContract"]["contractType"] not in [None, "None"] else "Wallet"
    #                     current_iter_dict["receiver_type"] = item["receiver"]["smartContract"][
    #                         "contractType"] if item["receiver"]["smartContract"]["contractType"] not in [None,
    #                                                                                                      "None"] else "Wallet"
    #                     if self.is_swaps(item):
    #                         possible_swaps.append(item)
    #                     flattened_response.append(current_iter_dict)
    #                     return
    #                 else:
    #                     current_iter_dict["tx_time"] = item["transaction"]["time"]["time"]
    #                     current_iter_dict["sender_type"] = item["sender"]["type"]
    #                     current_iter_dict["receiver_type"] = item["receiver"]["type"]
    #                     if self.chain in ["BNB", "TRX"]:
    #                         current_iter_dict["token"] = token_address
    #                         flattened_response.append(current_iter_dict)
    #                         return
    #                     if self.chain == "EOS":
    #                         current_iter_dict["token"] = item["currency"]["name"]
    #                         flattened_response.append(current_iter_dict)
    #                         return
    #                         # Once the loop has run its course, the flattened response array is returned

    def flatten_node(self, initial_depth, item, flattened_response, possible_swaps, token_address):
        """Process and flatten blockchain transaction data"""
        try:
            # Base transaction details common to all chains
            current_iter_dict = {
                "depth": int(safe_get(item, "depth", default=0)) + initial_depth,
                "tx_hash": safe_get(item, "transaction", "hash", default=""),
                "sender": safe_get(item, "sender", "address", default=""),
                "receiver": safe_get(item, "receiver", "address", default=""),
                "sender_annotation": safe_get(item, "sender", "annotation", default=""),
                "receiver_annotation": safe_get(item, "receiver", "annotation", default="")
            }

            # XRP and XLM processing
            if self.chain in ["XRP", "XLM"]:
                current_iter_dict.update({
                    "tx_time": safe_get(item, "transaction", "time", "time", default=""),
                    "sent_amount": safe_get(item, "amountFrom", default=0),
                    "sent_tx_value": safe_get(item, "transaction", "valueFrom", default=0),
                    "sent_currency": safe_get(item, "currencyFrom", "symbol", default=""),
                    "received_amount": safe_get(item, "amountTo", default=0),
                    "received_tx_value": safe_get(item, "transaction", "valueTo", default=0),
                    "received_currency": safe_get(item, "currencyTo", "symbol", default=""),
                    "operation_type": safe_get(item, "operation", default=""),
                    "receiver_receive_from_count": safe_get(item, "receiver", "receiversCount", default=0),
                    "receiver_send_to_count": safe_get(item, "receiver", "sendersCount", default=0),
                    "receiver_first_transfer_at": safe_get(item, "receiver", "firstTransferAt", "time"),
                    "receiver_last_transfer_at": safe_get(item, "receiver", "lastTransferAt", "time")
                })

                if self.chain == "XRP":
                    dest_tag = safe_get(item, "destinationTag")
                    if dest_tag:
                        current_iter_dict["destination_tag"] = dest_tag
                    source_tag = safe_get(item, "sourceTag")
                    if source_tag:
                        current_iter_dict["source_tag"] = source_tag

                flattened_response.append(current_iter_dict)
                return

            # Common fields for non-XRP/XLM chains
            current_iter_dict.update({
                "symbol": safe_get(item, "currency", "symbol", default=""),
                "amount": safe_get(item, "amount", default=0),
                "amount_usd": safe_get(item, "amount_usd", default=0)
            })

            # LUNC processing
            if self.chain == "LUNC":
                current_iter_dict.update({
                    "tx_time": safe_get(item, "block", "timestamp", "time", default=""),
                    "tx_value": safe_get(item, "transaction", "value", default=0)
                })
                flattened_response.append(current_iter_dict)
                return

            # Bitcoin-like chains processing
            if self.chain in ["BTC", "BCH", "LTC", "ADA", "DOGE", "ZEC", "DASH"]:
                if self.chain in ["BTC", "DOGE", "DASH"]:
                    if safe_get(item, "receiver", "type") == "coinbase" and not safe_get(item, "receiver", "address"):
                        return

                current_iter_dict.update({
                    "tx_time": safe_get(item, "transactions", 0, "timestamp", default=""),
                    "tx_value_in": safe_get(item, "transaction", "valueIn", default=0),
                    "tx_value_out": safe_get(item, "transaction", "valueOut", default=0)
                })

                if self.chain in ["BTC", "BCH", "LTC", "DOGE", "ZEC", "DASH"]:
                    current_iter_dict.update({
                        "sender_type": safe_get(item, "sender", "type", default="unknown"),
                        "receiver_type": safe_get(item, "receiver", "type", default="unknown")
                    })

                    if self.chain == "ZEC":
                        if current_iter_dict["sender"] == "" and current_iter_dict["sender_type"]:
                            current_iter_dict["sender"] = current_iter_dict["sender_type"]
                        if current_iter_dict["sender"] == "<shielded>" and current_iter_dict[
                            "sender_type"] == "shielded":
                            current_iter_dict["sender"] = "shielded"
                        if current_iter_dict["receiver"] == "" and current_iter_dict["receiver_type"]:
                            current_iter_dict["receiver"] = current_iter_dict["receiver_type"]
                        if current_iter_dict["receiver"] == "<shielded>" and current_iter_dict[
                            "receiver_type"] == "shielded":
                            current_iter_dict["receiver"] = "shielded"

                    flattened_response.append(current_iter_dict)
                    return

                elif self.chain == "ADA":
                    current_iter_dict.update({
                        "sender_type": "unknown",
                        "receiver_type": "unknown"
                    })
                    flattened_response.append(current_iter_dict)
                    return

            # Smart contract chains common fields
            current_iter_dict.update({
                "token_id": safe_get(item, "currency", "tokenId", default=""),
                "token_type": safe_get(item, "currency", "tokenType", default=""),
                "receiver_receivers_count": safe_get(item, "receiver", "receiversCount", default=0),
                "receiver_senders_count": safe_get(item, "receiver", "sendersCount", default=0),
                "receiver_first_tx_at": safe_get(item, "receiver", "firstTxAt", "time"),
                "receiver_last_tx_at": safe_get(item, "receiver", "lastTxAt", "time"),
                "receiver_amount_out": float(safe_get(item, "receiver", "amountOut", default=0)),
                "receiver_amount_in": float(safe_get(item, "receiver", "amountIn", default=0)),
                "receiver_balance": float(safe_get(item, "receiver", "balance", default=0))
            })

            # Ethereum-like chains
            if self.chain in ["ETH", "KLAY", "BSC", "FTM", "POL", "AVAX"]:
                current_iter_dict.update({
                    "token": token_address,
                    "tx_time": safe_get(item, "transactions", 0, "timestamp", default=""),
                    "sender_type": safe_get(item, "sender", "smartContract", "contractType", default="Wallet"),
                    "receiver_type": safe_get(item, "receiver", "smartContract", "contractType", default="Wallet")
                })

                if self.is_swaps(item):
                    possible_swaps.append(item)

                flattened_response.append(current_iter_dict)
                return

            # BNB, TRX, EOS chains
            current_iter_dict.update({
                "tx_time": safe_get(item, "transaction", "time", "time", default=""),
                "sender_type": safe_get(item, "sender", "type", default="unknown"),
                "receiver_type": safe_get(item, "receiver", "type", default="unknown")
            })

            if self.chain in ["BNB", "TRX"]:
                current_iter_dict["token"] = token_address
                flattened_response.append(current_iter_dict)
                return

            if self.chain == "EOS":
                current_iter_dict["token"] = safe_get(item, "currency", "name", default="")
                flattened_response.append(current_iter_dict)
                return

        except Exception as e:
            print(f"Error in flatten_node for chain {self.chain}: {str(e)}")

    def call_graphql_endpoint(self, address, token_address, from_time, initial_depth):

        if initial_depth >= int(self.depth):
            return []

        request_body = self._graphql_query_builder(address, token_address, from_time)
        if not request_body:
            print("Error while forming query")
            return []
        try:
            # flattened response is used to convert the GraphQL response format to REST API response format
            flattened_response = []
            possible_swaps = []
            print("graphql query: ", request_body)
            r = requests.post(self._graphql_endpoint, json={
                'query': request_body}, headers=self._headers, timeout=(self.connect_timeout, self.read_timeout))

            print(f"Bitquery query-id: {r.headers['x-graphql-query-id']}")
            response = r.json()
            for item in response["data"][Constants.NETWORK_CHAIN_MAPPING_FOR_RESPONSE[self.chain]]["coinpath"]:
                self.flatten_node(initial_depth, item, flattened_response, possible_swaps, token_address)

            return self.get_tx_with_swaps(flattened_response, possible_swaps)
        except Timeout:
            print(f"Bitquery Graphql call timed out for: {address} {self.chain}")
            error_resp = {'errors': [{'message': 'Bitquery request timed out'}]}
            return error_resp
        except RequestException:
            print(f"Bitquery Graphql call request exception: {address} {self.chain}")
            return []
        except Exception:
            traceback.print_exc()
            if "errors" in response and response["errors"]:
                print("Bitquery error response: ", response["errors"])
            return response