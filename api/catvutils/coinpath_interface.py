import traceback
from datetime import datetime
from multiprocessing.pool import ThreadPool

import requests
from requests.exceptions import Timeout, RequestException

from api import utils
from api.catvutils.graphql_interface import GraphQLInterface
from api.catvutils.tracer_interface import TracerAPIInterface
from api.constants import Constants
from api.settings import api_settings


class CoinpathAPIInterface:
    def __init__(self, is_ck_request=False):
        self.is_ck_request = is_ck_request
        self._graphql_key = api_settings.GRAPHQL_X_API_KEY
        self._graphql_endpoint = api_settings.GRAPHQL_ENDPOINT
        self.connect_timeout = 60
        self.read_timeout = 300
        self.ext_api_calls = 0
        self.api_used = 'bitquery'


    def transform_transaction_data(self, transactions):
        transformed_data = []
        
        for tx in transactions:
            
            transformed_tx = tx.copy()
            transformed_tx["amount"] = float(tx["amount"])  
            transformed_tx["token"] = ''
            if "token" in tx and tx["token"] is not None:
                transformed_tx["token"] = tx["token"]["address"]
            transformed_tx["tx_time"] = tx["tx_time"].replace("Z", "+00:00")  
            
            transformed_data.append(transformed_tx)
        
        return transformed_data

    def get_transactions(self, address, limit=10000, depth_limit=2, source=True, chain='ETH',
                         from_time=datetime(2015, 1, 1, 0, 0),
                         till_time=datetime.now(),
                         token_address=None):
        
        should_use_tracer_first = chain in ['ETH', 'BSC', 'FTM', 'POL', 'ETC', 'TRX', 'BTC']

        # Special case: If chain is BSC and there's a valid token address, don't use tracer first
        # if chain == 'BSC' and token_address is not None and token_address != "" and token_address != '0x0000000000000000000000000000000000000000':
        #     should_use_tracer_first = False
        
        if should_use_tracer_first:
            try:
                # Try Tracer API first
                tracer_interface = TracerAPIInterface()
                transaction_data = tracer_interface.get_transactions(
                    address,
                    limit,
                    0,
                    depth_limit,
                    from_time,
                    till_time,
                    token_address,
                    source,
                    chain,
                    self.is_ck_request
                )
                self.ext_api_calls += 1

                if transaction_data:
                    self.api_used = "tracer"
                    print(f"Tracer API successful: Retrieved {len(transaction_data)} transactions")
                    transformed_data = self.transform_transaction_data(transaction_data)
                    return [item for item in transformed_data if len(item["receiver"]) > 0]
                else:
                    print("Tracer API returned no data, falling back to Bitquery")

            except Exception as e:
                error_msg = f"Tracer API failed: {str(e)}. Falling back to Bitquery."
                print(error_msg)

        
        graphql_interface = GraphQLInterface(
            chain,
            source,
            depth_limit,
            till_time,
            limit,
            self.is_ck_request
        )
        initial_depth = 0
        results = graphql_interface.call_graphql_endpoint(address, token_address, from_time, initial_depth)
        if 'errors' in results and results['errors'] and 'message' in results['errors'][0]:
            error_msg = results['errors'][0]['message']
            if "Failed to find token" in error_msg:
                results = graphql_interface.call_graphql_endpoint(address, None, from_time, initial_depth)

        return results

