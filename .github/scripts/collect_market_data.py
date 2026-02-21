#!/usr/bin/env python3
"""GitHub Actions: collect market data and save as JSON files.

Usage:
    python3 .github/scripts/collect_market_data.py \
        --region japan \
        --output data/market \
        [--verbose]

Output layout:
    data/market/
      japan/
        _meta.json                  # last_updated, stock count, presets
        stocks/
          9984_T.json               # normalized stock info (cache-format)
          7203_T.json
          ...
        screen/
          value.json                # raw yf.screen() results for each preset
          high-dividend.json
          ...
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path so we can import src/
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent          # .github/scripts/
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent              # repo root
sys.path.insert(0, str(_PROJECT_ROOT))

import yfinance as yf                                  # noqa: E402
from yfinance import EquityQuery                       # noqa: E402

# ---------------------------------------------------------------------------
# Japan core stock universe (~80 major stocks by market cap)
# These are always collected regardless of screening results.
# ---------------------------------------------------------------------------
JAPAN_CORE_STOCKS = [
    # Mega-cap (>10兆円)
    "7203.T",   # Toyota Motor
    "9984.T",   # SoftBank Group
    "6758.T",   # Sony Group
    "8306.T",   # Mitsubishi UFJ Financial
    "6861.T",   # Keyence
    "9432.T",   # NTT (Nippon Telegraph)
    "9983.T",   # Fast Retailing (Uniqlo)
    "8316.T",   # Sumitomo Mitsui Financial (SMBC)
    "4063.T",   # Shin-Etsu Chemical
    "6098.T",   # Recruit Holdings
    # Large-cap
    "9433.T",   # KDDI
    "7974.T",   # Nintendo
    "4519.T",   # Chugai Pharmaceutical
    "4568.T",   # Daiichi Sankyo
    "6367.T",   # Daikin Industries
    "7741.T",   # HOYA
    "8035.T",   # Tokyo Electron
    "6594.T",   # Nidec (Nidec Corp)
    "7267.T",   # Honda Motor
    "7011.T",   # Mitsubishi Heavy Industries
    "4502.T",   # Takeda Pharmaceutical
    "8411.T",   # Mizuho Financial
    "9022.T",   # Central Japan Railway (JR Central)
    "6702.T",   # Fujitsu
    "6501.T",   # Hitachi
    "6503.T",   # Mitsubishi Electric
    "2914.T",   # Japan Tobacco International (JT)
    "9020.T",   # East Japan Railway (JR East)
    "5401.T",   # Nippon Steel
    "7751.T",   # Canon
    "8001.T",   # Itochu Corp
    "8031.T",   # Mitsui & Co.
    "8058.T",   # Mitsubishi Corp
    "8002.T",   # Marubeni Corp
    "6723.T",   # Renesas Electronics
    "6762.T",   # TDK Corp
    "6971.T",   # Kyocera Corp
    "3382.T",   # Seven & i Holdings
    "4661.T",   # Oriental Land (Tokyo Disney)
    "2802.T",   # Ajinomoto
    "4901.T",   # Fujifilm Holdings
    "9201.T",   # Japan Airlines (JAL)
    "9202.T",   # ANA Holdings
    "8604.T",   # Nomura Holdings
    "8766.T",   # Tokio Marine Holdings
    "8750.T",   # Dai-ichi Life Insurance
    "6301.T",   # Komatsu
    "7270.T",   # Subaru Corp
    "5108.T",   # Bridgestone
    "6857.T",   # Advantest
    "4543.T",   # Terumo Corp
    "4307.T",   # Nomura Research Institute
    "6146.T",   # Disco Corp
    "9613.T",   # NTT Data
    "4452.T",   # Kao Corp
    "3099.T",   # Marui Group
    "8267.T",   # Aeon Co.
    "1925.T",   # Daiwa House Industry
    "1928.T",   # Sekisui House
    "8830.T",   # Sumitomo Realty & Development
    "4578.T",   # Otsuka Holdings
    "6645.T",   # Omron Corp
    "7733.T",   # Olympus Corp
    "9021.T",   # West Japan Railway (JR West)
    "4151.T",   # Kyowa Kirin
    "3403.T",   # Toray Industries
    "6503.T",   # Mitsubishi Electric (dupe guard ok)
    "2269.T",   # Meiji Holdings
    "4021.T",   # Nissan Chemical
    "5714.T",   # Dowa Holdings
    "9602.T",   # Toho Co. (Cinema)
    "3086.T",   # J. Front Retailing
    "6490.T",   # Pillar Corp
    "7912.T",   # Dai Nippon Printing
    "7956.T",   # Pigeon Corp
    "4666.T",   # Park24
    "3289.T",   # Tokyu Fudosan Holdings
]

# Presets to run screening for
JAPAN_SCREEN_PRESETS = [
    "value",
    "high-dividend",
    "growth",
    "alpha",
    "quality",
    "shareholder-return",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _symbol_to_filename(symbol: str) -> str:
    """Convert ticker symbol to safe filename (e.g. 9984.T → 9984_T)."""
    return symbol.replace(".", "_").replace("/", "_")


def _normalize_ratio(val):
    """Convert percentage > 1 to ratio form."""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f or f == float("inf") or f == float("-inf"):  # NaN / inf guard
            return None
        if f > 1.0:
            return f / 100.0
        return f
    except (TypeError, ValueError):
        return None


def _safe_get(info: dict, *keys):
    """Return first non-None, finite value from info dict."""
    for key in keys:
        val = info.get(key)
        if val is None:
            continue
        try:
            f = float(val)
            if f != f or abs(f) == float("inf"):
                continue
            return f
        except (TypeError, ValueError):
            return val  # string values (name, sector) are OK
    return None


def _normalize_stock_info(symbol: str, info: dict) -> dict:
    """Normalize raw ticker.info dict into the application's canonical format.

    The output format matches exactly what src/data/yahoo_client/detail.py
    get_stock_info() returns, so it can be used as a drop-in replacement.
    """
    return {
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        # Price
        "price": _safe_get(info, "regularMarketPrice", "currentPrice"),
        "market_cap": _safe_get(info, "marketCap"),
        # Valuation
        "per": _safe_get(info, "trailingPE"),
        "forward_per": _safe_get(info, "forwardPE"),
        "pbr": _safe_get(info, "priceToBook"),
        "psr": _safe_get(info, "priceToSalesTrailing12Months"),
        # Profitability
        "roe": _safe_get(info, "returnOnEquity"),
        "roa": _safe_get(info, "returnOnAssets"),
        "profit_margin": _safe_get(info, "profitMargins"),
        "operating_margin": _safe_get(info, "operatingMargins"),
        # Dividend
        "dividend_yield": _normalize_ratio(_safe_get(info, "dividendYield")),
        "dividend_yield_trailing": _safe_get(info, "trailingAnnualDividendYield"),
        "payout_ratio": _safe_get(info, "payoutRatio"),
        # Growth
        "revenue_growth": _safe_get(info, "revenueGrowth"),
        "earnings_growth": _safe_get(info, "earningsGrowth"),
        # Financial health
        "debt_to_equity": _safe_get(info, "debtToEquity"),
        "current_ratio": _safe_get(info, "currentRatio"),
        "free_cashflow": _safe_get(info, "freeCashflow"),
        # Other
        "beta": _safe_get(info, "beta"),
        "fifty_two_week_high": _safe_get(info, "fiftyTwoWeekHigh"),
        "fifty_two_week_low": _safe_get(info, "fiftyTwoWeekLow"),
        # Market data timestamp
        "_market_data_updated": datetime.now(timezone.utc).isoformat(),
    }


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Fetch stock detail for one symbol
# ---------------------------------------------------------------------------

def fetch_stock_info(symbol: str, verbose: bool = False) -> dict | None:
    """Fetch and normalize stock info for a single symbol."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info or info.get("regularMarketPrice") is None:
            if verbose:
                print(f"  ⚠ {symbol}: no regularMarketPrice in response")
            return None
        result = _normalize_stock_info(symbol, info)
        return result
    except Exception as e:
        if verbose:
            print(f"  ✗ {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# Run screening for a preset
# ---------------------------------------------------------------------------

PRESET_QUERIES_JAPAN = {
    "value": EquityQuery("and", [
        EquityQuery("lt", ["peratio.lasttwelvemonths", 15]),
        EquityQuery("lt", ["pricebookratio.quarterly", 1.5]),
        EquityQuery("gt", ["forward_dividend_yield", 0.02]),
        EquityQuery("gt", ["returnonequity.lasttwelvemonths", 0.05]),
        EquityQuery("eq", ["region", "jp"]),
    ]),
    "high-dividend": EquityQuery("and", [
        EquityQuery("gt", ["forward_dividend_yield", 0.03]),
        EquityQuery("lt", ["peratio.lasttwelvemonths", 20]),
        EquityQuery("eq", ["region", "jp"]),
    ]),
    "growth": EquityQuery("and", [
        EquityQuery("gt", ["returnonequity.lasttwelvemonths", 0.15]),
        EquityQuery("gt", ["totalrevenues1yrgrowth.lasttwelvemonths", 0.10]),
        EquityQuery("gt", ["epsgrowth.lasttwelvemonths", 0.10]),
        EquityQuery("eq", ["region", "jp"]),
    ]),
    "quality": EquityQuery("and", [
        EquityQuery("lt", ["peratio.lasttwelvemonths", 15]),
        EquityQuery("lt", ["pricebookratio.quarterly", 1.5]),
        EquityQuery("gt", ["returnonequity.lasttwelvemonths", 0.15]),
        EquityQuery("gt", ["forward_dividend_yield", 0.02]),
        EquityQuery("eq", ["region", "jp"]),
    ]),
    "alpha": EquityQuery("and", [
        EquityQuery("lt", ["peratio.lasttwelvemonths", 20]),
        EquityQuery("lt", ["pricebookratio.quarterly", 2.0]),
        EquityQuery("gt", ["returnonequity.lasttwelvemonths", 0.08]),
        EquityQuery("eq", ["region", "jp"]),
    ]),
    "shareholder-return": EquityQuery("and", [
        EquityQuery("lt", ["peratio.lasttwelvemonths", 20]),
        EquityQuery("gt", ["forward_dividend_yield", 0.02]),
        EquityQuery("eq", ["region", "jp"]),
    ]),
}


def run_screen_preset(preset_name: str, verbose: bool = False) -> list[dict]:
    """Run yf.screen() for a preset and return raw quote list."""
    query = PRESET_QUERIES_JAPAN.get(preset_name)
    if query is None:
        print(f"  ⚠ Unknown preset: {preset_name}")
        return []
    try:
        response = yf.screen(
            query, size=100, offset=0,
            sortField="intradaymarketcap", sortAsc=False,
        )
        if response is None:
            return []
        quotes = response.get("quotes", [])
        if verbose:
            print(f"  preset={preset_name}: {len(quotes)} stocks")
        return quotes
    except Exception as e:
        if verbose:
            print(f"  ✗ screen preset={preset_name}: {e}")
        return []


# ---------------------------------------------------------------------------
# Main collection logic
# ---------------------------------------------------------------------------

def collect_region(region: str, output_dir: Path, verbose: bool) -> dict:
    """Collect market data for a region and return summary."""
    if region != "japan":
        print(f"[collect] Region '{region}' not yet supported (only 'japan')")
        return {}

    stocks_dir = output_dir / region / "stocks"
    screen_dir = output_dir / region / "screen"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    screen_dir.mkdir(parents=True, exist_ok=True)

    updated_at = datetime.now(timezone.utc).isoformat()
    collected_symbols: set[str] = set()

    # --- Step 1: Run screening presets ---
    print(f"\n[collect] Running {len(JAPAN_SCREEN_PRESETS)} screening presets for {region}...")
    screen_results: dict[str, list] = {}
    for preset in JAPAN_SCREEN_PRESETS:
        if verbose:
            print(f"  Screening: {preset}")
        quotes = run_screen_preset(preset, verbose=verbose)
        screen_results[preset] = quotes
        # Save raw screening result
        screen_data = {
            "_updated": updated_at,
            "_preset": preset,
            "_region": region,
            "results": quotes,
        }
        _write_json(screen_dir / f"{preset}.json", screen_data)
        # Collect symbols for detail fetch
        for q in quotes:
            sym = q.get("symbol")
            if sym:
                collected_symbols.add(sym)
        time.sleep(1)  # rate-limit

    # Add core list
    collected_symbols.update(JAPAN_CORE_STOCKS)
    # Deduplicate (already a set)
    symbols_to_fetch = sorted(collected_symbols)
    print(f"\n[collect] Fetching detail for {len(symbols_to_fetch)} stocks...")

    # --- Step 2: Fetch individual stock details ---
    success = 0
    failed = 0
    for i, symbol in enumerate(symbols_to_fetch, 1):
        if verbose:
            print(f"  [{i}/{len(symbols_to_fetch)}] {symbol}", end=" ")
        info = fetch_stock_info(symbol, verbose=False)
        if info is not None:
            fname = _symbol_to_filename(symbol) + ".json"
            _write_json(stocks_dir / fname, info)
            success += 1
            if verbose:
                price = info.get("price")
                name = info.get("name", "")
                print(f"✓ {name} @ {price}")
        else:
            failed += 1
            if verbose:
                print("✗ no data")
        time.sleep(0.5)  # rate-limit: ~0.5s per stock

    # --- Step 3: Write metadata ---
    meta = {
        "_updated": updated_at,
        "region": region,
        "stocks_collected": success,
        "stocks_failed": failed,
        "presets_screened": JAPAN_SCREEN_PRESETS,
        "symbols": sorted(collected_symbols),
    }
    _write_json(output_dir / region / "_meta.json", meta)

    print(f"\n[collect] {region}: ✓ {success} stocks, ✗ {failed} failed")
    return meta


def main():
    parser = argparse.ArgumentParser(description="Collect market data for offline use")
    parser.add_argument("--region", default="japan",
                        help="Region to collect: japan, us, all (default: japan)")
    parser.add_argument("--output", default="data/market",
                        help="Output directory (default: data/market)")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()

    output_dir = _PROJECT_ROOT / args.output
    regions = ["japan"] if args.region != "all" else ["japan"]

    print(f"[collect] Starting market data collection → {output_dir}")
    for region in regions:
        collect_region(region, output_dir, verbose=args.verbose)

    print("\n[collect] Done.")


if __name__ == "__main__":
    main()
