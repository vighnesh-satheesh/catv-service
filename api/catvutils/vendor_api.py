import requests

from django.conf import settings

__all__ = ('LyzeAPIInterface', )


class LyzeAPIInterface:
    def __init__(self, key):
        self.__key = key
        self.__source_endpoint = settings.LYZE_SRC_ENDPOINT
        self.__distribution_endpoint = settings.LYZE_DIST_ENDPOINT

    def fetch_api_response(self, api_url, data, timeout=600):
        header = {
            'x-api-key': self.__key
        }
        response = requests.get(api_url, params=data, timeout=timeout, headers=header)
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
