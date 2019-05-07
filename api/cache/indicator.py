from django.core.cache import caches

class IndicatorCache:
    def __init__(self):
        pass

    def set_indicator(self, pattern, data, security_category):
        indicator_cache = caches['local_indicator']
        indicator_target_cache = caches['local_indicator_{security_category}'.format(security_category=security_category)]

        indicator_cache.set(pattern, security_category)
        indicator_target_cache.set(pattern, data)

    def get_indicator(self, pattern):
        c = caches['local_indicator']
        return c.get(pattern)

    def get_blacklist_indicator(self, pattern):
        c = caches['local_indicator_blacklist']
        return c.get(pattern)

    def get_whitelist_indicator(self, pattern):
        c = caches['local_indicator_whitelist']
        return c.get(pattern)
