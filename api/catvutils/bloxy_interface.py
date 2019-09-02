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
        response_list = response.json()
        return response_list

    def get_transactions(self, address, depth_limit=2, from_time=datetime(2015, 1, 1, 0, 0), till_time=datetime.now(),
                         token_address=None, source=True):
        if source:
            api_url = self._source_endpoint
            depth = depth_limit - 1
        else:
            api_url = self._distribution_endpoint
            depth = depth_limit

        payload = {'key': self._key, 'address': address, 'depth_limit': depth,
                   'from_time': from_time, 'till_time': till_time, 'snapshot_time': from_time if source else till_time,
                   'limit_address_tx_count': 100000, 'limit': 100000}
        if token_address:
            payload['token_address'] = token_address
        r = self.call_bloxy_api(api_url, payload)
        return r
