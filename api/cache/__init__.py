from django.core.cache import caches, cache
import random, string
import re
from urllib.parse import urlparse


class DefaultCache:
    def __init__(self):
        pass

    def get_cache(self):
        return caches["default"]

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

    def set_password_reset_key(self, email):
        previous = self.get(email + "-password")
        if not previous:
            self.delete_key(previous)
        v = "".join(random.choice(string.ascii_letters) for x in range(40))
        self.set(email + "-password", v, 60 * 5)
        self.set(v, email + "-password", 60 * 5)
        return v

    def set_signup_verification_key(self, email):
        previous = self.get(email + "-activate")
        if not previous:
            self.delete_key(previous)
        v = "".join(random.choice(string.ascii_letters) for x in range(40))
        self.set(email + "-activate", v, 60 * 5)
        self.set(v, email + "-activate", 60 * 5)
        return v


class UppwardCache:
    def __init__(self):
        pass

    def invalidate_cache(self, u):
        c = caches["uppward"]
        p = re.compile(r"^((https?:\/\/[^\s/$.?#][^\s]*)|((([a-z0-9]|[^\x00-\x7F])([a-z0-9-]|[^\x00-\x7F])*\.)+([a-z]|[^\x00-\x7F])([a-z0-9-]|[^\x00-\x7F]){1,}(:\d{1,5})?(\/.*)?))$", re.IGNORECASE)
        if p.match(u) != None:
            url = urlparse(u).netloc.replace("www.", "").lower()
            d = c.get(url)
            if d is not None:
                c.delete(url)
            d = c.get('www.' + url)
            if d is not None:
                c.delete('www' + url)
