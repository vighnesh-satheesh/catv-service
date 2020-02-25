from datetime import datetime
import requests

from django.conf import settings

__all__ = ('LyzeAPIInterface', 'BloxyBTCAPIInterface', 'BloxyEthAPIInterface', )


class LyzeAPIInterface:
    def __init__(self, key):
        self.__key = key
        self.__source_endpoint = settings.LYZE_SRC_ENDPOINT
        self.__distribution_endpoint = settings.LYZE_DIST_ENDPOINT
        self.__txlist_endpoint = settings.LYZE_TXLIST_ENDPOINT

    def fetch_api_response(self, api_url, data, timeout=600):
        header = {
            'x-api-key': self.__key
        }
        response = requests.get(api_url, params=data, timeout=timeout, headers=header)
        if response.status_code != 200:
            print(response)
            return []
        response_list = response.json()
        return response_list["body"].get("result", [])

    def get_transactions(self, address, limit, tx_hash, depth_limit=2, source=True):
        api_url = self.__source_endpoint if source else self.__distribution_endpoint

        payload = {
            "address": address,
            "limit": limit,
            "depth_limit": depth_limit,
            "tx_id": tx_hash
        }
        r = self.fetch_api_response(api_url, payload)
        return r

    def get_txlist(self, address, from_date=None, to_date=None):
        from_time = datetime.now().strftime('%Y%m%d_000000')
        to_time = datetime.now().strftime('%Y%m%d_235959')
        if from_date is not None:
            from_time = datetime.strptime(from_date, '%Y-%m-%d')
            from_time = from_time.strftime('%Y%m%d_000000')
        if to_date is not None:
            to_time = datetime.strptime(to_date, '%Y-%m-%d')
            to_time = to_time.strftime('%Y%m%d_235959')

        payload = {
            "wallet_address": address,
            "from_time": from_time,
            "to_time": to_time
        }
        r = self.fetch_api_response(self.__txlist_endpoint, payload)
        return r


class BloxyBTCAPIInterface:
    def __init__(self, key):
        self.__key = key
        self.__source_endpoint = settings.BLOXY_BTC_SRC_ENDPOINT
        self.__distribution_endpoint = settings.BLOXY_BTC_DIST_ENDPOINT

    def fetch_api_response(self, api_url, data, timeout=600):
        response = requests.get(api_url, params=data, timeout=timeout)
        if response.status_code != 200:
            print(response)
            return []
        response_list = response.json()
        return response_list

    def get_transactions(self, address, tx_limit, limit, depth_limit=2, from_time=datetime(2015, 1, 1, 0, 0),
                         till_time=datetime.now(), source=True):
        api_url = self.__source_endpoint if source else self.__distribution_endpoint
        depth = depth_limit
        payload = {'key': self.__key, 'address': address, 'depth_limit': depth,
                   'from_date': from_time, 'till_date': till_time, 'snapshot_time': from_time if source else till_time,
                   'limit_address_tx_count': tx_limit, 'limit': limit, 'format': 'json'}
        r = self.fetch_api_response(api_url, payload)
        return r


class BloxyEthAPIInterface:
    def __init__(self, key):
        self.__key = key
        self.__coinpath_endpoint = settings.BLOXY_ETHCOINPATH_ENDPOINT

    def fetch_api_response(self, api_url, data, timeout=600):
        response = requests.get(api_url, params=data, timeout=timeout)
        if response.status_code != 200:
            print(response)
            return []
        response_list = response.json()
        return response_list

    def get_path_transactions(self, path_tracker):
        api_url = self.__coinpath_endpoint
        payload = {
            'key': self.__key,
            'address1': path_tracker.address_from,
            'address2': path_tracker.address_to,
            'depth_limit': path_tracker.depth_limit,
            'min_tx_amount': path_tracker.min_tx_amount,
            'from_date': path_tracker.from_date,
            'till_date': path_tracker.to_date,
            'limit_address_tx_count': path_tracker.limit_address_tx,
            'format': 'json'
        }
        if path_tracker.token_address:
            payload.update({'token': path_tracker.token_address})

        r = self.fetch_api_response(api_url, payload)
        return r

