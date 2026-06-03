"""Tiny TTL cache for hot filesystem scans.

Per-process. Single-threaded reasoning is fine because FastAPI's threadpool
serializes Python execution under the GIL — at worst we recompute a value
twice if two threads miss simultaneously, which is harmless."""
from __future__ import annotations

import time
from functools import wraps
from typing import Callable

# (key) -> (expires_at, value)
_STORE: dict = {}


def ttl_cache(seconds: float):
    """Decorator. Caches by (fn name, args, sorted kwargs)."""
    def deco(fn: Callable):
        @wraps(fn)
        def wrap(*args, **kwargs):
            key = (fn.__qualname__, args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            hit = _STORE.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]
            value = fn(*args, **kwargs)
            _STORE[key] = (now + seconds, value)
            return value
        wrap.cache_clear = lambda: _clear_for(fn.__qualname__)  # type: ignore[attr-defined]
        return wrap
    return deco


def _clear_for(qualname: str) -> None:
    for k in list(_STORE.keys()):
        if k[0] == qualname:
            del _STORE[k]


def clear_all() -> None:
    _STORE.clear()
