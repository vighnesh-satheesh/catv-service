import traceback
from datetime import datetime
from multiprocessing.pool import ThreadPool

import requests
from requests.exceptions import Timeout, RequestException

from api import utils
from api.catvutils.graphql_interface import GraphQLInterface
from api.constants import Constants
from api.settings import api_settings


class BloxyAPIInterface:
    def __init__(self, is_ck_request=False):
        self.is_ck_request = is_ck_request
        self._graphql_key = api_settings.GRAPHQL_X_API_KEY
        self._graphql_endpoint = api_settings.GRAPHQL_ENDPOINT
        self.connect_timeout = 60
        self.read_timeout = 300

    def get_transactions(self, address, limit=10000, depth_limit=2, source=True, chain='ETH',
                         from_time=datetime(2015, 1, 1, 0, 0),
                         till_time=datetime.now(),
                         token_address=None):
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

