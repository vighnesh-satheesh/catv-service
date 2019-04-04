from django.core.cache import caches, cache
import random, string

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
        self.set(email + "-activate", v, 60 * 60)
        self.set(v, email + "-activate", 60 * 60)
        return v

    def get_view_cache(self, request):
        c = self.get_cache()
        key = request.get_full_path()
        d = c.get(key)
        return d if d is not None else None

    def set_view_cache(self, request, value, time=60*60):
        c = self.get_cache()
        key = request.get_full_path()
        c.set(key, value, time)
        return value

    def delete_view_cache(self, request):
        c = self.get_cache()
        key = request.get_full_path()
        c.delete(key)
