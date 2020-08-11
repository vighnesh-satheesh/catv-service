import requests
from datetime import datetime

from django.conf import settings


class BloxyAPIInterface:
    def __init__(self, key):
        self._key = key
        self._source_endpoint = settings.BLOXY_SRC_ENDPOINT
        self._distribution_endpoint = settings.BLOXY_DIST_ENDPOINT

    def call_bloxy_api(self, api_url, data, timeout=600):
        response = requests.get(api_url, params=data, timeout=timeout)
        if response.status_code != 200:
            print(response)
            return []
        response_list = response.json()
        print(response_list)
        return response_list

    def get_transactions(self, address, tx_limit, limit, depth_limit=2, from_time=datetime(2015, 1, 1, 0, 0), till_time=datetime.now(),
                         token_address=None, source=True, chain='ETH'):
        if source:
            api_url = self._source_endpoint
            depth = depth_limit - 1
        else:
            api_url = self._distribution_endpoint
            depth = depth_limit
        
        updated_chain = chain.lower()
        if updated_chain == 'trx':
            updated_chain = 'tron'

        payload = {'key': self._key, 'address': address, 'depth_limit': depth,
                   'from_time': from_time, 'till_time': till_time, 'snapshot_time': from_time if source else till_time,
                   'limit_address_tx_count': tx_limit, 'limit': limit, 'chain': updated_chain}
        print(payload)
        if token_address:
            payload['token_address'] = token_address
        r = self.call_bloxy_api(api_url, payload)
        return r
