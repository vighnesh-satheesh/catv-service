from django.core.cache import caches
import subprocess

class IndicatorCache:
    def __init__(self):
        pass

    def get_last_indicator_id(self):
        indicator_cache = caches['local_indicator']
        return indicator_cache.get('last_indicator_id')

    def set_last_indicator_id(self, id):
        indicator_cache = caches['local_indicator']
        indicator_cache.set('last_indicator_id', id, 0)

    def clear_last_indicator_id(self):
        indicator_cache = caches['local_indicator']
        indicator_cache.delete('last_indicator_id')

    def set_indicator(self, pattern, data, security_category):
        indicator_cache = caches['local_indicator']
        indicator_cache.set(pattern, security_category, 0)

    def get_indicator(self, pattern):
        c = caches['local_indicator']
        return c.get(pattern)

    def clear_indicator(self):
        subprocess.call(['redis-cli', '-n', '10', 'FLUSHDB'])
