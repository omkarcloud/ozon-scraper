"""A small in-memory response cache with the hosted service's interface
(`cached_call`, `DontCache`). ozon/api.py stores one row per upstream page
for the TTLs in ozon/cache_config.py, so repeated calls — and the question
pages, which follow a cursor from the previous page — don't refetch.
Everything lives in this process and is gone on restart."""
import json
import threading
import time

_rows = {}
_lock = threading.Lock()
MAX_ROWS = 2000


class DontCache:
    """Wrap a result to return it without storing it."""

    def __init__(self, data):
        self.data = data


def _key(namespace, data):
    return namespace + ":" + json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)


def cached_call(namespace, data, fn, ttl, cache=True, refresh=False):
    """fn(**data), served from memory for `ttl` (a timedelta)."""
    key = _key(namespace, data)
    now = time.monotonic()
    if cache and ttl and not refresh:
        with _lock:
            hit = _rows.get(key)
        if hit and hit[0] > now:
            return hit[1]
    result = fn(**data)
    if isinstance(result, DontCache):
        return result.data
    if cache and ttl:
        seconds = ttl.total_seconds() if hasattr(ttl, "total_seconds") else float(ttl)
        with _lock:
            if len(_rows) >= MAX_ROWS:
                for stale in [k for k, (exp, _) in _rows.items() if exp <= now] or list(_rows)[:MAX_ROWS // 10]:
                    _rows.pop(stale, None)
            _rows[key] = (now + seconds, result)
    return result
