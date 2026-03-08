"""Simple in-memory TTL cache for nba_api calls."""

import time
import threading

_cache: dict[str, tuple] = {}  # key -> (value, expiry_timestamp)
_lock = threading.Lock()


def cached_api_call(key: str, fetch_fn, ttl: int = 300):
    """Fetch data with caching. Returns cached result if available and not expired.

    Args:
        key: Unique cache key (e.g., "PlayerGameLog:player_id:season")
        fetch_fn: Callable that fetches the data (called only on cache miss)
        ttl: Time-to-live in seconds (default 5 minutes)

    Returns:
        The fetched data (from cache or fresh)
    """
    now = time.time()

    with _lock:
        if key in _cache:
            value, expiry = _cache[key]
            if now < expiry:
                return value

    # Cache miss - fetch fresh data
    result = fetch_fn()

    with _lock:
        _cache[key] = (result, now + ttl)

    return result


def clear_cache():
    """Clear all cached data."""
    with _lock:
        _cache.clear()


def cache_stats() -> dict:
    """Get cache statistics."""
    with _lock:
        now = time.time()
        total = len(_cache)
        active = sum(1 for _, (_, exp) in _cache.items() if now < exp)
        return {"total_entries": total, "active_entries": active, "expired_entries": total - active}
