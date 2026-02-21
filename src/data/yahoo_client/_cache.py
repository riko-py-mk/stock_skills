"""Cache helpers for yahoo_client (KIK-449)."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


CACHE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "cache"
CACHE_TTL_HOURS = 24


def _is_network_error(exc: Exception) -> bool:
    """Return True if the exception looks like a network / proxy block error.

    Distinguishes transient network failures (tunnel blocked, SSL error,
    connection refused, DNS failure) from data-level errors (invalid symbol,
    unexpected API response).  Used to decide whether to fall back to stale
    cached data instead of returning None immediately.
    """
    msg = str(exc).lower()
    network_keywords = (
        "tunnel",
        "connect",
        "ssl",
        "connection refused",
        "name or service not known",
        "nodename nor servname",
        "network is unreachable",
        "errno 110",
        "errno 111",
        "errno 113",
        "timed out",
        "timeout",
        "proxy",
        "403",
        "curl",
    )
    return any(kw in msg for kw in network_keywords)


def _cache_path(symbol: str) -> Path:
    """Return the cache file path for a given symbol."""
    safe_name = symbol.replace(".", "_").replace("/", "_")
    return CACHE_DIR / f"{safe_name}.json"


def _read_cache(symbol: str) -> Optional[dict]:
    """Read cached data if it exists and is still valid."""
    path = _cache_path(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
        if datetime.now() - cached_at > timedelta(hours=CACHE_TTL_HOURS):
            return None
        return data
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def _write_cache(symbol: str, data: dict) -> None:
    """Write data to cache with a timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["_cached_at"] = datetime.now().isoformat()
    path = _cache_path(symbol)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_stale_cache(symbol: str) -> Optional[dict]:
    """Read cached data ignoring TTL expiry (stale fallback).

    Returns cached data even if it is older than CACHE_TTL_HOURS, or None if
    no cache file exists at all.  The returned dict is tagged with
    ``_stale=True`` so callers can display a staleness warning.
    """
    path = _cache_path(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_stale"] = True
        return data
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Detail cache helpers
# ---------------------------------------------------------------------------

def _detail_cache_path(symbol: str) -> Path:
    """Return the detail-cache file path for a given symbol."""
    safe_name = symbol.replace(".", "_").replace("/", "_")
    return CACHE_DIR / f"{safe_name}_detail.json"


def _read_detail_cache(symbol: str) -> Optional[dict]:
    """Read detail-cached data if it exists and is still valid (24h TTL)."""
    path = _detail_cache_path(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
        if datetime.now() - cached_at > timedelta(hours=CACHE_TTL_HOURS):
            return None
        return data
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def _write_detail_cache(symbol: str, data: dict) -> None:
    """Write detail data to cache with a timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["_cached_at"] = datetime.now().isoformat()
    path = _detail_cache_path(symbol)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_stale_detail_cache(symbol: str) -> Optional[dict]:
    """Read detail cached data ignoring TTL expiry (stale fallback).

    Returns cached data even if older than CACHE_TTL_HOURS, or None if no
    cache file exists.  Tags the result with ``_stale=True``.
    """
    path = _detail_cache_path(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_stale"] = True
        return data
    except (json.JSONDecodeError, ValueError, KeyError):
        return None
