"""Market data client: reads pre-collected JSON files from data/market/.

GitHub Actions collects market data daily (see .github/workflows/collect-market-data.yml)
and commits the results to data/market/{region}/stocks/{symbol}.json.

This client provides a fallback for environments where live Yahoo Finance API
access is restricted (e.g., sandboxed CI with a proxy allowlist).

Fallback priority (in detail.py):
  1. Fresh local cache (data/cache/)
  2. Live Yahoo Finance API
  3. Stale local cache (data/cache/, TTL ignored)
  4. Pre-collected market data file  ← this module     (local data/market/ OR raw.githubusercontent.com)

The raw.githubusercontent.com domain is in the proxy allowlist, so remote
fetching works even in sandboxed environments.

Environment variables
---------------------
GITHUB_MARKET_DATA_REPO : str
    GitHub repository in "owner/repo" format used to build the
    raw.githubusercontent.com URL.  Defaults to auto-detection via
    ``git remote get-url origin``.
GITHUB_MARKET_DATA_BRANCH : str
    Branch where market data files are committed (default: "main").
"""

import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_MARKET_DATA_DIR = _PROJECT_ROOT / "data" / "market"

# ---------------------------------------------------------------------------
# GitHub raw URL configuration
# ---------------------------------------------------------------------------
_GITHUB_REPO_ENV = os.environ.get("GITHUB_MARKET_DATA_REPO", "").strip()
_GITHUB_BRANCH = os.environ.get("GITHUB_MARKET_DATA_BRANCH", "main").strip()

# Cache the detected repo so we only run git once per process
_detected_repo: Optional[str] = None


def _detect_github_repo() -> Optional[str]:
    """Auto-detect GitHub owner/repo from git remote URL.

    Returns a string like "owner/repo" or None if detection fails.
    """
    global _detected_repo
    if _detected_repo is not None:
        return _detected_repo or None

    if _GITHUB_REPO_ENV:
        _detected_repo = _GITHUB_REPO_ENV
        return _detected_repo

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=str(_PROJECT_ROOT), timeout=5,
        )
        if result.returncode != 0:
            _detected_repo = ""
            return None
        url = result.stdout.strip()
        # Parse https://github.com/owner/repo.git  or  git@github.com:owner/repo.git
        for prefix in ("https://github.com/", "http://github.com/"):
            if url.startswith(prefix):
                path = url[len(prefix):].rstrip("/").removesuffix(".git")
                _detected_repo = path
                return _detected_repo
        if "github.com:" in url:
            path = url.split("github.com:")[-1].rstrip("/").removesuffix(".git")
            _detected_repo = path
            return _detected_repo
        _detected_repo = ""
        return None
    except Exception:
        _detected_repo = ""
        return None


def _symbol_to_filename(symbol: str) -> str:
    return symbol.replace(".", "_").replace("/", "_") + ".json"


# ---------------------------------------------------------------------------
# Local file reader
# ---------------------------------------------------------------------------

def _read_local(region: str, symbol: str) -> Optional[dict]:
    """Read stock info from local data/market/{region}/stocks/{file}."""
    path = _MARKET_DATA_DIR / region / "stocks" / _symbol_to_filename(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_from_market_data"] = True
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _read_local_screen(region: str, preset: str) -> Optional[list[dict]]:
    """Read pre-collected screening results for a region+preset."""
    path = _MARKET_DATA_DIR / region / "screen" / f"{preset}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("results", [])
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Remote fetcher (raw.githubusercontent.com — in proxy allowlist)
# ---------------------------------------------------------------------------

def _fetch_remote(path_in_repo: str) -> Optional[dict | list]:
    """Fetch a JSON file from raw.githubusercontent.com.

    Parameters
    ----------
    path_in_repo : str
        Path relative to repo root, e.g. "data/market/japan/stocks/9984_T.json"
    """
    repo = _detect_github_repo()
    if not repo:
        return None
    url = (
        f"https://raw.githubusercontent.com/{repo}/{_GITHUB_BRANCH}/{path_in_repo}"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "stock-skills-market-data-client/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None


def _read_remote(region: str, symbol: str) -> Optional[dict]:
    """Fetch stock info from raw.githubusercontent.com."""
    path = f"data/market/{region}/stocks/{_symbol_to_filename(symbol)}"
    data = _fetch_remote(path)
    if isinstance(data, dict):
        data["_from_market_data"] = True
        return data
    return None


def _read_remote_screen(region: str, preset: str) -> Optional[list[dict]]:
    """Fetch screening results from raw.githubusercontent.com."""
    path = f"data/market/{region}/screen/{preset}.json"
    data = _fetch_remote(path)
    if isinstance(data, dict):
        return data.get("results", [])
    return None


def _read_meta_remote(region: str) -> Optional[dict]:
    """Fetch _meta.json from raw.githubusercontent.com."""
    path = f"data/market/{region}/_meta.json"
    data = _fetch_remote(path)
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_stock_info(symbol: str, region: str = "japan") -> Optional[dict]:
    """Return pre-collected stock info for a symbol.

    Tries local data/market/ first, then raw.githubusercontent.com.
    Returns None if no pre-collected data is available.

    The returned dict format matches exactly what
    src/data/yahoo_client/detail.py get_stock_info() returns.
    """
    # 1. Local file (fast, works when data/market/ is up-to-date after git pull)
    local = _read_local(region, symbol)
    if local is not None:
        return local

    # 2. Remote fetch via raw.githubusercontent.com (works in sandboxed envs)
    remote = _read_remote(region, symbol)
    return remote


def get_screen_results(region: str, preset: str) -> Optional[list[dict]]:
    """Return pre-collected screening results for a region+preset.

    Returns None if no pre-collected data is available.
    The returned list contains raw yf.screen() quote dicts.
    """
    local = _read_local_screen(region, preset)
    if local is not None:
        return local
    return _read_remote_screen(region, preset)


def get_meta(region: str) -> Optional[dict]:
    """Return metadata about the most recent collection for a region."""
    path = _MARKET_DATA_DIR / region / "_meta.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return _read_meta_remote(region)


def get_data_age_hours(region: str = "japan") -> Optional[float]:
    """Return age of most recent market data collection in hours, or None."""
    meta = get_meta(region)
    if meta is None:
        return None
    updated = meta.get("_updated")
    if not updated:
        return None
    try:
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        return (now - dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None
