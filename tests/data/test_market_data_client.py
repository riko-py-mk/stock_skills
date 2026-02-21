"""Tests for src/data/market_data_client.py (file-based, no network calls)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data import market_data_client as mdc
from src.data.market_data_client import (
    _symbol_to_filename,
    _read_local,
    _read_local_screen,
    get_stock_info,
    get_screen_results,
    get_meta,
    get_data_age_hours,
)

_MARKET_DATA_DIR_PATCH = "src.data.market_data_client._MARKET_DATA_DIR"


# ---------------------------------------------------------------------------
# _symbol_to_filename
# ---------------------------------------------------------------------------

class TestSymbolToFilename:
    def test_dot_replaced(self):
        assert _symbol_to_filename("9984.T") == "9984_T.json"

    def test_slash_replaced(self):
        assert _symbol_to_filename("D05.SI") == "D05_SI.json"

    def test_plain_us_symbol(self):
        assert _symbol_to_filename("AAPL") == "AAPL.json"

    def test_double_dot(self):
        assert _symbol_to_filename("7203.T") == "7203_T.json"


# ---------------------------------------------------------------------------
# _read_local
# ---------------------------------------------------------------------------

class TestReadLocal:
    def test_returns_none_when_file_missing(self, tmp_path):
        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            assert _read_local("japan", "9984.T") is None

    def test_reads_existing_file(self, tmp_path):
        stocks_dir = tmp_path / "japan" / "stocks"
        stocks_dir.mkdir(parents=True)
        data = {"symbol": "9984.T", "price": 4440.0, "_market_data_updated": "2026-02-21"}
        (stocks_dir / "9984_T.json").write_text(json.dumps(data))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            result = _read_local("japan", "9984.T")
        assert result is not None
        assert result["price"] == 4440.0

    def test_sets_from_market_data_flag(self, tmp_path):
        stocks_dir = tmp_path / "japan" / "stocks"
        stocks_dir.mkdir(parents=True)
        data = {"symbol": "7203.T", "price": 2850.0}
        (stocks_dir / "7203_T.json").write_text(json.dumps(data))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            result = _read_local("japan", "7203.T")
        assert result is not None
        assert result["_from_market_data"] is True

    def test_corrupt_json_returns_none(self, tmp_path):
        stocks_dir = tmp_path / "japan" / "stocks"
        stocks_dir.mkdir(parents=True)
        (stocks_dir / "BAD_T.json").write_text("{corrupt")

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            assert _read_local("japan", "BAD.T") is None


# ---------------------------------------------------------------------------
# _read_local_screen
# ---------------------------------------------------------------------------

class TestReadLocalScreen:
    def test_returns_none_when_missing(self, tmp_path):
        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            assert _read_local_screen("japan", "value") is None

    def test_reads_screen_results(self, tmp_path):
        screen_dir = tmp_path / "japan" / "screen"
        screen_dir.mkdir(parents=True)
        data = {
            "_updated": "2026-02-21",
            "_preset": "value",
            "results": [{"symbol": "7203.T"}, {"symbol": "9984.T"}],
        }
        (screen_dir / "value.json").write_text(json.dumps(data))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            result = _read_local_screen("japan", "value")
        assert result is not None
        assert len(result) == 2
        assert result[0]["symbol"] == "7203.T"

    def test_empty_results_returns_empty_list(self, tmp_path):
        screen_dir = tmp_path / "japan" / "screen"
        screen_dir.mkdir(parents=True)
        data = {"_updated": "2026-02-21", "_preset": "value", "results": []}
        (screen_dir / "value.json").write_text(json.dumps(data))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            result = _read_local_screen("japan", "value")
        assert result == []


# ---------------------------------------------------------------------------
# get_stock_info (local path, no remote)
# ---------------------------------------------------------------------------

class TestGetStockInfoLocal:
    def test_returns_local_data(self, tmp_path):
        stocks_dir = tmp_path / "japan" / "stocks"
        stocks_dir.mkdir(parents=True)
        data = {"symbol": "9984.T", "price": 4440.0}
        (stocks_dir / "9984_T.json").write_text(json.dumps(data))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            # Disable remote fetch so test is deterministic
            with patch.object(mdc, "_read_remote", return_value=None):
                result = get_stock_info("9984.T", region="japan")
        assert result is not None
        assert result["price"] == 4440.0
        assert result["_from_market_data"] is True

    def test_falls_back_to_remote_when_no_local(self, tmp_path):
        remote_data = {"symbol": "AAPL", "price": 250.0, "_from_market_data": True}
        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            with patch.object(mdc, "_read_remote", return_value=remote_data):
                result = get_stock_info("AAPL", region="us")
        assert result is not None
        assert result["price"] == 250.0

    def test_returns_none_when_no_data_anywhere(self, tmp_path):
        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            with patch.object(mdc, "_read_remote", return_value=None):
                result = get_stock_info("UNKNOWN.T", region="japan")
        assert result is None


# ---------------------------------------------------------------------------
# get_screen_results
# ---------------------------------------------------------------------------

class TestGetScreenResults:
    def test_returns_local_screen_data(self, tmp_path):
        screen_dir = tmp_path / "japan" / "screen"
        screen_dir.mkdir(parents=True)
        data = {"_updated": "2026-02-21", "_preset": "value",
                "results": [{"symbol": "7203.T"}]}
        (screen_dir / "value.json").write_text(json.dumps(data))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            with patch.object(mdc, "_read_remote_screen", return_value=None):
                result = get_screen_results("japan", "value")
        assert result is not None
        assert result[0]["symbol"] == "7203.T"

    def test_falls_back_to_remote(self, tmp_path):
        remote = [{"symbol": "6758.T"}]
        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            with patch.object(mdc, "_read_remote_screen", return_value=remote):
                result = get_screen_results("japan", "growth")
        assert result == remote

    def test_returns_none_when_no_data(self, tmp_path):
        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            with patch.object(mdc, "_read_remote_screen", return_value=None):
                result = get_screen_results("japan", "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# get_data_age_hours
# ---------------------------------------------------------------------------

class TestGetDataAgeHours:
    def test_returns_none_when_no_meta(self, tmp_path):
        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            with patch.object(mdc, "_read_meta_remote", return_value=None):
                assert get_data_age_hours("japan") is None

    def test_returns_float_for_recent_data(self, tmp_path):
        from datetime import datetime, timezone, timedelta
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        meta = {"_updated": one_hour_ago, "region": "japan"}
        meta_path = tmp_path / "japan" / "_meta.json"
        meta_path.parent.mkdir(parents=True)
        meta_path.write_text(json.dumps(meta))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            age = get_data_age_hours("japan")
        assert age is not None
        assert 0.9 < age < 1.1  # roughly 1 hour

    def test_handles_invalid_timestamp(self, tmp_path):
        meta = {"_updated": "not-a-date"}
        meta_path = tmp_path / "japan" / "_meta.json"
        meta_path.parent.mkdir(parents=True)
        meta_path.write_text(json.dumps(meta))

        with patch(_MARKET_DATA_DIR_PATCH, tmp_path):
            assert get_data_age_hours("japan") is None
