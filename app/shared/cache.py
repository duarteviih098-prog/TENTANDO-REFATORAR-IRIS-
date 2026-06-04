"""Cache leve de views/queries."""
import threading
import time

from app.db import query_all, query_one

CACHE_TTL_SECONDS = 60
_view_cache = {}
_cache_lock = threading.Lock()

def clear_view_cache(prefix=None):
    with _cache_lock:
        if not prefix:
            _view_cache.clear()
            return
        for key in list(_view_cache.keys()):
            if str(key).startswith(prefix):
                _view_cache.pop(key, None)


def cached_result(key, producer, ttl=CACHE_TTL_SECONDS):
    now = time.time()
    with _cache_lock:
        cached = _view_cache.get(key)
        if cached and now - cached['ts'] < ttl:
            return cached['value']
    value = producer()
    with _cache_lock:
        _view_cache[key] = {'ts': now, 'value': value}
    return value


def cached_query_all(key, sql, params=(), ttl=CACHE_TTL_SECONDS):
    return cached_result(key, lambda: query_all(sql, params), ttl=ttl)


def cached_query_one(key, sql, params=(), ttl=CACHE_TTL_SECONDS):
    return cached_result(key, lambda: query_one(sql, params), ttl=ttl)
