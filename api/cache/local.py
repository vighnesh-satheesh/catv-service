from django.core.cache import caches
import subprocess

class LocalCache:
    def __init__(self):
        pass

    def get_cache(self):
        return caches["local_cache"]

    def delete_key(self, key):
        c = self.get_cache()
        c.delete(key)

    def set(self, key, value, timeout):
        c = self.get_cache()
        c.set(key, value, timeout)
        return

    def get(self, key):
        c = self.get_cache()
        d = c.get(key)
        return d

    def has(self, key):
        c = self.get_cache()
        d = c.get(key)
        return True if d is not None else False

    def clear(self):
        subprocess.call(['redis-cli', '-n', '10', 'FLUSHDB'])
