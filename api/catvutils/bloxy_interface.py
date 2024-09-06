import traceback
from datetime import datetime

import requests
from django.conf import settings
from requests.exceptions import Timeout, RequestException

from api import utils
from api.constants import Constants
from api.settings import api_settings


class BloxyAPIInterface:
    def __init__(self, key):
        self._key = key
        self._source_endpoint_eth = settings.BLOXY_SRC_ENDPOINT
        self._distribution_endpoint_eth = settings.BLOXY_DIST_ENDPOINT
        self._source_endpoint_btc = settings.BLOXY_BTC_SRC_ENDPOINT
        self._distribution_endpoint_btc = settings.BLOXY_BTC_DIST_ENDPOINT
        self._graphql_key = api_settings.GRAPHQL_X_API_KEY
        self._graphql_endpoint = api_settings.GRAPHQL_ENDPOINT
        self.connect_timeout = 60
        self.read_timeout = 300

    def call_bloxy_api(self, api_url, data):
        print('api_url:', api_url)
        print("Payload: ", data)
        try:
            # The verify flag is set to false because of an issue with sending requests to this endpoint
            res = requests.get(api_url, params=data, timeout=(self.connect_timeout, self.read_timeout), verify=False)
            if res.status_code != 200:
                print(res)
                return []
            response = res.json()
            return response
        except Timeout:
            print("Bitquery API call timed out for: ", data)
            return []
        except RequestException:
            print("Bitquery API call request exception: ", data)
            return []
        except Exception as e:
            traceback.print_exc()
            return []

    def get_transactions(self, address, tx_limit=10000, limit=10000, depth_limit=2, source=True, chain='ETH',
                         from_time=datetime(2015, 1, 1, 0, 0),
                         till_time=datetime.now(),
                         token_address=None):
        graphql_interface = GraphQLInterfaceUnified(
            chain,
            source,
            address,
            token_address,
            depth_limit,
            from_time,
            till_time,
            limit
        )
        results = graphql_interface.call_graphql_endpoint()
        return results


class GraphQLInterfaceUnified:

    def __init__(self, chain, source, address, token_address, depth_limit, from_time, till_time, limit):
        self._graphql_key = api_settings.GRAPHQL_X_API_KEY
        self._graphql_endpoint = api_settings.GRAPHQL_ENDPOINT
        self._headers = {'X-API-KEY': self._graphql_key}
        self.token_address = token_address
        self.chain = chain
        self.source = source
        self.address = address
        self.depth = depth_limit
        from_time = utils.validate_dateformat_and_randomize_seconds(from_time, "%Y-%m-%dT%H:%M:%S")
        self.from_time = str(from_time).replace(" ", "T")
        self.till_time = str(till_time).replace(" ", "T")
        self.limit = int(limit)
        self.connect_timeout = 60
        self.read_timeout = 300

    def _graphql_query_builder(self):
        # define the direction of transaction flow:
        direction = "inbound" if self.source else "outbound"
        # define starter query parameter modules (these will be modified based on the chain)
        amount_details = " amountOut amountIn balance "
        smart_contract = " smartContract { contractType } "
        common_receiver_query = " receiver { address annotation receiversCount sendersCount "
        # Adding the params common to most blockchains first, these are modified later
        currency = " "
        receiver = "receiver { address annotation } "
        sender = receiver.replace("receiver", "sender")
        extra_params = " depth amount amount_usd: amount(in: USD) currency { symbol } "
        time = " var { time } "
        if self.token_address is not None and self.token_address != "" and self.token_address != '0x0000000000000000000000000000000000000000':
            currency_value = self.token_address
        else:
            currency_value = Constants.GRAPHQL_CURRENCY_MAPPING.get(self.chain, None)
        network = Constants.NETWORK_CHAIN_MAPPING_FOR_RESPONSE[self.chain] + \
                  " (network: " + Constants.NETWORK_CHAIN_MAPPING_FOR_QUERY[self.chain] + " ) "
        destination_tag = " "
        source_tag = " "
        try:
            # Cardano or ADA
            if self.chain == "ADA":
                transaction = " transaction { hash valueIn valueOut } transactions { timestamp } "
            #  TERRA or LUNC
            elif self.chain == "LUNC":
                transaction = """ transaction { hash value } block { timestamp { time ( format: "%Y-%m-%d" ) } } """
            # Ripple/Stellar or XRP/XLM
            elif self.chain in ["XRP", "XLM"]:
                receiver = common_receiver_query + time.replace("var", "firstTransferAt") + " " + \
                           time.replace("var", "lastTransferAt") + " } "
                sender = " sender { address annotation " + time.replace("var", "firstTransferAt") + " " + \
                         time.replace("var", "lastTransferAt") + " } "
                transaction = " transaction { hash " + time.replace("var", "time") + " valueFrom valueTo  }"
                extra_params = " depth  amountFrom amountTo operation currencyFrom { name symbol } currencyTo { name symbol } "
                if self.chain == "XRP":
                    destination_tag = " destinationTag"
                    source_tag = " sourceTag"
            # Bitcoin Cash/Litecoin or BCH/LTC
            elif self.chain in ["BTC", "BCH", "LTC", "DOGE", "ZEC", "DASH"]:
                receiver = common_receiver_query + time.replace("var", "firstTxAt") + \
                           " " + time.replace("var", "lastTxAt") + " type } "
                sender = " sender { address annotation type " + \
                         time.replace("var", "firstTxAt") + \
                         " " + time.replace("var", "lastTxAt") + " } "
                transaction = " transaction { hash  valueIn valueOut } transactions { timestamp } "
            # EOS
            elif self.chain == "EOS":
                receiver = common_receiver_query + time.replace("var", "firstTxAt") + \
                           " " + time.replace("var", "lastTxAt") + " type " + amount_details + " } "
                sender = " sender { address annotation type } "
                transaction = " transaction { hash value " + time.replace("var", "time") + " } "
                extra_params = " depth amount amount_usd: amount(in: USD) currency { name symbol tokenId tokenType } "
                # Klaytn/Binance Smart Chain or KLAY/BSC
            elif self.chain in ["ETH", "KLAY", "BSC", "FTM", "POL", "AVAX"]:
                currency = f""" currency: {{ is: "{currency_value}" }} """ if currency_value else " "
                receiver = common_receiver_query + amount_details + \
                           time.replace("var", "firstTxAt") + " " + \
                           time.replace("var", "lastTxAt") + \
                           " type " + smart_contract + " } "
                sender = " sender { address annotation type " + amount_details + smart_contract + " }"
                transaction = " transaction { hash value } " + \
                              " transactions { timestamp txHash txValue amount height } "
                extra_params = " depth amount amount_usd: amount(in: USD) currency { name symbol tokenId tokenType address } "

                # Binance Coin/Tron or BNB/TRX
            elif self.chain in ["BNB", "TRX"]:
                currency = f""" currency: {{ is: "{currency_value}" }} """
                receiver = common_receiver_query + time.replace("var", "firstTxAt") + \
                           " " + time.replace("var", "lastTxAt") + " type " + amount_details + " } "
                sender = " sender { address annotation type } "
                network = network if self.chain == "TRX" else Constants.NETWORK_CHAIN_MAPPING_FOR_RESPONSE[self.chain]
                transaction = " transaction { hash value " + time.replace("var", "time") + " } "
                extra_params = " depth amount amount_usd: amount(in: USD) currency { name symbol tokenId tokenType } "

            # building final GraphQL query
            GRAPHQL_QUERY = f"""
                query sentinel_query {{
                    {network} {{
                        coinpath(
                        options: {{ direction: {direction}, asc: "depth", limit: {self.limit} }}
                        initialAddress: {{ is: "{self.address}" }}
                        depth: {{ lteq: {self.depth} }}
                        date: {{ since: "{self.from_time}", till: "{self.till_time}" }}
                        {currency}
                        ) {{
                            {destination_tag}
                            {source_tag}
                            {receiver}
                            {sender}
                            {transaction}
                            {extra_params}
                        }}
                    }}
                }}   
                """
            return GRAPHQL_QUERY
        except Exception as e:
            traceback.print_exc()
            return None

    def call_graphql_endpoint(self):
        request_body = self._graphql_query_builder()
        if request_body is None or len(request_body) == 0:
            print("Error while forming query")
            return []
        try:
            # flattened response is used to convert the GraphQL response format to REST API response format
            flattened_response = []
            r = requests.post(self._graphql_endpoint, json={
                'query': request_body}, headers=self._headers, timeout=(self.connect_timeout, self.read_timeout))
            response = r.json()
            print("graphql query: ", request_body)
            for item in response["data"][Constants.NETWORK_CHAIN_MAPPING_FOR_RESPONSE[self.chain]]["coinpath"]:
                # These dict items are common to all response bodies
                # After this, the code enters the nested if-else block and the other parameters are assigned

                # Once all parameters have been assinged to current_iter_dict, it is appended to the
                # flattened response array, and the loop continues
                current_iter_dict = {
                    "depth": item["depth"],
                    "tx_hash": item["transaction"]["hash"],
                    "sender": item["sender"]["address"],
                    "receiver": item["receiver"]["address"],
                    "sender_annotation": item["sender"]["annotation"] if item["sender"]["annotation"] not in [None,
                                                                                                              "None"] else "",
                    "receiver_annotation": item["receiver"]["annotation"] if item["receiver"]["annotation"] not in [
                        None, "None"] else ""
                }
                # XRP and XLM have the same parameters so they are grouped together
                if self.chain in ["XRP", "XLM"]:
                    current_iter_dict["tx_time"] = item["transaction"]["time"]["time"]
                    current_iter_dict["sent_amount"] = item["amountFrom"]
                    current_iter_dict["sent_tx_value"] = item["transaction"]["valueFrom"]
                    current_iter_dict["sent_currency"] = item["currencyFrom"]["symbol"]
                    current_iter_dict["received_amount"] = item["amountTo"]
                    current_iter_dict["received_tx_value"] = item["transaction"]["valueTo"]
                    current_iter_dict["received_currency"] = item["currencyTo"]["symbol"]
                    current_iter_dict["operation_type"] = item["operation"]
                    current_iter_dict["receiver_receive_from_count"] = item["receiver"]["receiversCount"]
                    current_iter_dict["receiver_send_to_count"] = item["receiver"]["sendersCount"]
                    current_iter_dict["receiver_first_transfer_at"] = item["receiver"]["firstTransferAt"]["time"]
                    current_iter_dict["receiver_last_transfer_at"] = item["receiver"]["lastTransferAt"]["time"]
                    if self.chain == "XRP" and item.get("destinationTag"):
                        current_iter_dict["destination_tag"] = item["destinationTag"]
                    if self.chain == "XRP" and item.get("sourceTag"):
                        current_iter_dict["source_tag"] = item["sourceTag"]
                    flattened_response.append(current_iter_dict)
                    continue
                else:
                    # The symbol and amount/amount_usd parameters are common to all except XRP and XLM, they are assigned here itself
                    current_iter_dict["symbol"] = item["currency"]["symbol"]
                    current_iter_dict["amount"] = item["amount"]
                    current_iter_dict["amount_usd"] = item["amount_usd"]
                    if self.chain == "LUNC":
                        current_iter_dict["tx_time"] = item["block"]["timestamp"]["time"]
                        current_iter_dict["tx_value"] = item["transaction"]["value"]
                        flattened_response.append(current_iter_dict)
                        continue
                    else:
                        # BCH, LTC, DOGE, ZEC, DASH and ADA have almost all parameters in common
                        # except sender_type and receiver_type
                        if self.chain in ["BTC", "BCH", "LTC", "ADA", "DOGE", "ZEC", "DASH"]:
                            current_iter_dict["tx_time"] = item["transactions"][0]["timestamp"]
                            current_iter_dict["tx_value_in"] = item["transaction"]["valueIn"]
                            current_iter_dict["tx_value_out"] = item["transaction"]["valueOut"]

                            if self.chain in ["BTC", "BCH", "LTC", "DOGE", "ZEC", "DASH"]:
                                current_iter_dict["sender_type"] = item["sender"]["type"]
                                current_iter_dict["receiver_type"] = item["receiver"]["type"]
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
                                continue
                            elif self.chain == "ADA":
                                current_iter_dict["sender_type"] = "unknown"
                                current_iter_dict["receiver_type"] = "unknown"
                                flattened_response.append(current_iter_dict)
                                continue
                        else:
                            # the parameters below are common to all the following blockchains
                            current_iter_dict["token_id"] = item["currency"]["tokenId"]
                            current_iter_dict["token_type"] = item["currency"]["tokenType"]
                            current_iter_dict["receiver_receivers_count"] = item["receiver"]["receiversCount"]
                            current_iter_dict["receiver_senders_count"] = item["receiver"]["sendersCount"]
                            current_iter_dict["receiver_first_tx_at"] = item["receiver"]["firstTxAt"]["time"]
                            current_iter_dict["receiver_last_tx_at"] = item["receiver"]["lastTxAt"]["time"]
                            current_iter_dict["receiver_amount_out"] = float(item["receiver"]["amountOut"])
                            current_iter_dict["receiver_amount_in"] = float(item["receiver"]["amountIn"])
                            current_iter_dict["receiver_balance"] = float(item["receiver"]["balance"])
                            if self.chain in ["ETH", "KLAY", "BSC", "FTM", "POL", "AVAX"]:
                                current_iter_dict["token"] = self.token_address
                                current_iter_dict["tx_time"] = item["transactions"][0]["timestamp"]
                                current_iter_dict["sender_type"] = item["sender"]["smartContract"]["contractType"] if \
                                    item["sender"]["smartContract"]["contractType"] not in [None, "None"] else "Wallet"
                                current_iter_dict["receiver_type"] = item["receiver"]["smartContract"][
                                    "contractType"] if item["receiver"]["smartContract"]["contractType"] not in [None,
                                                                                                                 "None"] else "Wallet"
                                flattened_response.append(current_iter_dict)
                                continue
                            else:
                                current_iter_dict["tx_time"] = item["transaction"]["time"]["time"]
                                current_iter_dict["sender_type"] = item["sender"]["type"]
                                current_iter_dict["receiver_type"] = item["receiver"]["type"]
                                if self.chain in ["BNB", "TRX"]:
                                    current_iter_dict["token"] = self.token_address
                                    flattened_response.append(current_iter_dict)
                                    continue
                                if self.chain == "EOS":
                                    current_iter_dict["token"] = item["currency"]["name"]
                                    flattened_response.append(current_iter_dict)
                                    continue
                                    # Once the loop has run its course, the flattened response array is returned
            return flattened_response
        except Timeout:
            print(f"Bitquery Graphql call timed out for: {self.address} {self.chain}")
            error_resp = {'errors': [{'message': 'Bitquery request timed out'}]}
            return error_resp
        except RequestException:
            print(f"Bitquery Graphql call request exception: {self.address} {self.chain}")
            return []
        except Exception:
            if "errors" in response and response["errors"]:
                print("Bitquery error response: ", response["errors"])
            traceback.print_exc()
            return response
