import requests
from datetime import datetime

from django.conf import settings


class BloxyAPIInterface:
    def __init__(self, key):
        self._key = key
        self._source_endpoint = settings.BLOXY_SRC_ENDPOINT
        self._distribution_endpoint = settings.BLOXY_DIST_ENDPOINT

    def call_bloxy_api(self, api_url, data, timeout=600):
        print(api_url)
        print(data)
        response = requests.get(api_url, params=data, timeout=timeout, verify=False)
        if response.status_code != 200:
            print(response)
            return []
        response_list = response.json()
        return response_list

    def get_transactions(self, address, tx_limit, limit, depth_limit=2, 
                        from_time=datetime(2015, 1, 1, 0, 0), 
                        till_time=datetime.now(),
                        token_address=None, source=True, chain='ETH'):
        if source:
            api_url = settings.BLOXY_ETH_SRC_ENDPOINT if (
                                            chain == 'ETH' or 
                                            chain == 'BSC' or 
                                            chain == 'KLAYTN'
                                        ) else self._source_endpoint
            depth = depth_limit
        else:
            api_url = settings.BLOXY_ETH_DIST_ENDPOINT if (
                                            chain == 'ETH' or 
                                            chain == 'BSC' or 
                                            chain == 'KLAYTN'
                                        ) else self._distribution_endpoint
            depth = depth_limit
        
        updated_chain_map = {
            'trx': 'tron',
            'xrp': 'ripple',
            'xlm': 'stellar',
            'bnb': 'binance',
            'ada': 'cardano'
        }
        
        updated_chain = chain.lower()
        if updated_chain in updated_chain_map.keys():
            updated_chain = updated_chain_map[updated_chain]
        
        if updated_chain == 'ripple' or updated_chain == 'stellar':
            api_url = api_url.replace('coinpath', 'ripple:sentinel')

        payload = {'key': self._key, 'address': address, 'depth_limit': depth,
                   'from_date': from_time, 'till_date': till_time, 'snapshot_time': from_time if source else till_time,
                   'limit_address_tx_count': tx_limit, 'limit': limit, 'chain': updated_chain}
        if token_address:
            if chain == 'ETH' or chain == 'BSC' or chain == 'KLAYTN':
                payload['token_address'] = token_address
            else:
                payload['token'] = token_address
        print("Payload : ", payload)
        r = self.call_bloxy_api(api_url, payload)
        return r
