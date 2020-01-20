from datetime import datetime
import requests

from django.conf import settings

__all__ = ('LyzeAPIInterface', )


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

    def get_transactions(self, address, limit, depth_limit=2, source=True):
        api_url = self.__source_endpoint if source else self.__distribution_endpoint

        payload = {
            "address": address,
            "limit": limit,
            "depth_limit": depth_limit
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
