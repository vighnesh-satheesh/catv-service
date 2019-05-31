from django.core.cache import caches
import subprocess


class TrackingCache:
    def __init__(self):
        pass

    def get_cache_entry(self, pattern):
        catv_cache = caches['catv_data']
        return catv_cache.get(pattern)

    def set_cache_entry(self, pattern, value, timeout=300):
        catv_cache = caches['catv_data']
        catv_cache.set(pattern, value, timeout)

    def delete_cache_entry(self, pattern):
        catv_cache = caches['catv_data']
        catv_cache.delete(pattern)
