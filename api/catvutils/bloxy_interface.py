import requests
import traceback
from datetime import datetime
from ..settings import api_settings
from django.conf import settings
from api.models import CatvTokens


class BloxyAPIInterface:
    def __init__(self, key):
        self._key = key
        self._source_endpoint_eth = settings.BLOXY_SRC_ENDPOINT
        self._distribution_endpoint_eth = settings.BLOXY_DIST_ENDPOINT
        self._source_endpoint_btc = settings.BLOXY_BTC_SRC_ENDPOINT
        self._distribution_endpoint_btc = settings.BLOXY_BTC_DIST_ENDPOINT
        self._graphql_key = settings.GRAPHQL_X_API_KEY
        self._graphql_endpoint = api_settings.GRAPHQL_ENDPOINT

    def call_bloxy_api(self, api_url, data, timeout=600):
        print('api_url:', api_url)
        res = requests.get(api_url, params=data, timeout=timeout, verify=False)
        if res.status_code != 200:
            print(res)
            return []
        response = res.json()
        return response

    def get_transactions(self, address, tx_limit=10000, limit=10000, depth_limit=2, source=True, chain='ETH',
                         from_time=datetime(2015, 1, 1, 0, 0),
                         till_time=datetime.now(),
                         token_address=None
                        ):
        if chain == 'ETH' or chain == 'BTC':
            payload = {
                'key': self._key,
                'address': address,
                'depth_limit': depth_limit,
                'from_date': from_time,
                'till_date': till_time,
                'limit': limit,
                'chain': chain.lower()
            }
            if chain == 'ETH':
                api_url = self._source_endpoint_eth if source else self._distribution_endpoint_eth
                if token_address:
                    payload['token_address'] = token_address
            elif chain == 'BTC':
                api_url = self._source_endpoint_btc if source else self._distribution_endpoint_btc
            print("Payload: ", payload)
            print("api_url:", api_url)
            r = self.call_bloxy_api(api_url, payload)
            return r
        else:
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
        self._graphql_key = settings.GRAPHQL_X_API_KEY
        self._graphql_endpoint = api_settings.GRAPHQL_ENDPOINT
        print(f"settings.GRAPHQL_ENDPOINT : {api_settings.GRAPHQL_ENDPOINT}")
        self._headers = {'X-API-KEY': self._graphql_key}
        self.token_address = token_address
        self.chain = chain
        self.source = source
        self.address = address
        self.depth = depth_limit
        self.from_time = str(from_time).replace(" ", "T")
        self.till_time = str(till_time).replace(" ", "T")
        self.limit = int(limit)
        self.network_chain_mapping_query = {
            "LUNC": "cosmos",
            "KLAY": "klaytn",
            "BSC": "bsc",
            "BNB": "binance",
            "TRX": "tron",
            "EOS": "eos",
            "XLM": "stellar",
            "XRP": "ripple",
            "LTC": "litecoin",
            "BCH": "bitcash",
            "ADA": "cardano"
        }
        self.network_chain_mapping_response = {
            "LUNC": "cosmos",
            "KLAY": "ethereum",
            "BSC": "ethereum",
            "BNB": "binance",
            "TRX": "tron",
            "EOS": "eos",
            "XLM": "stellar",
            "XRP": "ripple",
            "LTC": "bitcoin",
            "BCH": "bitcoin",
            "ADA": "cardano"
        }

    def _graphql_query_builder(self):
        # define the direction of transaction flow:
        direction = "inbound" if self.source else "outbound"
        # define starter query parameter modules (these will be modified based on the chain)
        initial_receiver_query = " receiver { address annotation "
        initial_sender_query = " sender { address annotation "
        initial_transaction_query = " transaction { hash value "
        initial_extra_params = " depth amount "
        amount_details = " amountOut amountIn balance "
        smart_contract = " smartContract { contractType } "
        time = " var { time } "
        currency_value = "BNB" if self.chain == "BSC" else self.chain
        if self.token_address is not None and self.token_address != "" and self.token_address != '0x0000000000000000000000000000000000000000':
            currency_value = self.token_address
        network = self.network_chain_mapping_response[self.chain] + \
                  " (network: " + self.network_chain_mapping_query[self.chain] + " ) "

        # starting the flow with Terra since it has the shortest request body
        try:
            # Cardano (ADA)
            if self.chain == "ADA":
                currency = " "
                receiver = initial_receiver_query + " } "
                sender = initial_sender_query + " } "
                transaction = initial_transaction_query.replace("value", " valueIn valueOut }") + \
                              " transactions { timestamp } "
                extra_params = initial_extra_params + " currency { symbol } "
            else:
                #  TERRA OR LUNC
                if self.chain == "LUNC":
                    currency = " "
                    receiver = initial_receiver_query + " } "
                    sender = initial_sender_query + " } "
                    transaction = initial_transaction_query + " } "
                    block = """ block { timestamp { time ( format: "%Y-%m-%d" ) } } """
                    transaction = transaction + block
                    extra_params = initial_extra_params + " currency { symbol }"
                else:
                    receiver = initial_receiver_query + " receiversCount sendersCount "
                    # Ripple and Stellar or XRP and XLM
                    if self.chain in ["XRP", "XLM"]:
                        currency = " "
                        receiver = receiver + \
                                   time.replace("var", "firstTransferAt") + " " + \
                                   time.replace("var", "lastTransferAt") + " } "
                        sender = initial_sender_query + \
                                 time.replace("var", "firstTransferAt") + " " + \
                                 time.replace("var", "lastTransferAt") + " } "
                        transaction = initial_transaction_query.replace("value", " ")
                        transaction = transaction + \
                                      time.replace("var", "time") + " " + \
                                      " valueFrom valueTo  }"
                        extra_params = initial_extra_params.replace("amount", " amountFrom amountTo operation")
                        extra_params = extra_params + " currencyFrom { name symbol } currencyTo { name symbol } "
                    else:
                        receiver = receiver + time.replace("var", "firstTxAt") + \
                                   " " + time.replace("var", "lastTxAt") + " type "
                        sender = initial_sender_query + " type "
                        # Bitcoin Cash and Litecoin or BCH and LTC
                        if self.chain in ["BCH", "LTC"]:
                            currency = " "
                            receiver = receiver + " } "
                            sender = sender + \
                                     time.replace("var", "firstTxAt") + \
                                     " " + time.replace("var", "lastTxAt") + " } "
                            transaction = initial_transaction_query.replace("value", " valueIn valueOut }") + \
                                          " transactions { timestamp } "
                            extra_params = initial_extra_params + " currency { symbol } "
                        else:
                            extra_params = initial_extra_params + " currency { name symbol tokenId tokenType "
                            receiver = receiver + amount_details
                            if self.chain in ["KLAY", "BSC"]:
                                currency = f""" currency: {{ is: "{currency_value}" }} """
                                receiver = receiver + smart_contract + " } "
                                sender = sender + smart_contract + " }"
                                transaction = initial_transaction_query + " } " + \
                                              " transactions { timestamp txHash txValue amount height } "
                                extra_params = extra_params + "address } "
                            else:
                                # after every else, similar fields are modified and grouped
                                receiver = receiver + " } "
                                sender = sender + " } "
                                transaction = initial_transaction_query + time.replace("var", "time") + " } "
                                if self.chain in ["BNB", "TRX"]:
                                    network = network if self.chain == "TRX" else self.network_chain_mapping_response[
                                        self.chain]
                                    currency = f""" currency: {{ is: "{currency_value}" }} """
                                    extra_params = extra_params + " address } "
                                else:
                                    if self.chain == "EOS":
                                        currency = " "
                                        extra_params = extra_params + " } "
                                    else:
                                        print("Error while forming query inside query builder module")
                                        return None

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
            print(f"Query is : {request_body}")
            print(f"GQL END POINT : {self._graphql_endpoint}")
            print(f"HEADER : {self._headers}")
            r = requests.post(self._graphql_endpoint, json={
                'query': request_body}, headers=self._headers)
            print("GQL Response: ", r)
            response = r.json()
            print(f"RESPONSE : {response}")
            for item in response["data"][self.network_chain_mapping_response[self.chain]]["coinpath"]:
                current_iter_dict = {
                    "depth": item["depth"],
                    "tx_hash": item["transaction"]["hash"],
                    "sender": item["sender"]["address"],
                    "receiver": item["receiver"]["address"],
                    "sender_annotation": item["sender"]["annotation"] if item["sender"]["annotation"] not in [None,
                                                                                                   "None"] else "",
                    "receiver_annotation": item["receiver"]["annotation"] if item["receiver"]["annotation"] not in [None,
                                                                                                         "None"] else ""
                }
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
                    flattened_response.append(current_iter_dict)
                    continue
                else:
                    current_iter_dict["symbol"] = item["currency"]["symbol"]
                    current_iter_dict["amount"] = item["amount"]
                    if self.chain == "LUNC":
                        current_iter_dict["tx_time"] = item["block"]["timestamp"]["time"]
                        current_iter_dict["tx_value"] = item["transaction"]["value"]
                        flattened_response.append(current_iter_dict)
                        continue
                    else:
                        if self.chain in ["BCH", "LTC", "ADA"]:
                            current_iter_dict["tx_time"] = item["transactions"][0]["timestamp"]
                            current_iter_dict["tx_value_in"] = item["transaction"]["valueIn"]
                            current_iter_dict["tx_value_out"] = item["transaction"]["valueOut"]
                            if self.chain in ["BCH", "LTC"]:
                                current_iter_dict["sender_type"] = item["sender"]["type"]
                                current_iter_dict["receiver_type"] = item["receiver"]["type"]
                                flattened_response.append(current_iter_dict)
                                continue
                            else:
                                if self.chain == "ADA":
                                    current_iter_dict["sender_type"] = "unknown"
                                    current_iter_dict["receiver_type"] = "unknown"
                                    flattened_response.append(current_iter_dict)
                                    continue
                                else:
                                    print("Unable to identify the chain")
                                    return []
                        else:
                            current_iter_dict["token_id"] = item["currency"]["tokenId"]
                            current_iter_dict["token_type"] = item["currency"]["tokenType"]
                            current_iter_dict["receiver_receivers_count"] = item["receiver"]["receiversCount"]
                            current_iter_dict["receiver_senders_count"] = item["receiver"]["sendersCount"]
                            current_iter_dict["receiver_first_tx_at"] = item["receiver"]["firstTxAt"]["time"]
                            current_iter_dict["receiver_last_tx_at"] = item["receiver"]["lastTxAt"]["time"]
                            current_iter_dict["receiver_amount_out"] = float(item["receiver"]["amountOut"])
                            current_iter_dict["receiver_amount_in"] = float(item["receiver"]["amountIn"])
                            current_iter_dict["receiver_balance"] = float(item["receiver"]["balance"])
                            if self.chain in ["KLAY", "BSC"]:
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
                                else:
                                    if self.chain == "EOS":
                                        current_iter_dict["token"] = item["currency"]["name"]
                                        flattened_response.append(current_iter_dict)
                                        continue
                                    else:
                                        print("Unable to identify the chain")
                                        return []
            return flattened_response
        except Exception as e:
            traceback.print_exc()
            return []
