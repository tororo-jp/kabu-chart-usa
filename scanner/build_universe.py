"""Build NYSE + NASDAQ universe with sector filtering.

Fetches all common stocks from NASDAQ trader files, enriches with sector/name
data via yfinance, then saves:
  stocks/sector_map.json  — {ticker: {sector, name}} for all tickers
  stocks/universe.txt     — filtered tickers (excluded sectors removed)

Run:
  python scanner/build_universe.py
  python scanner/build_universe.py --sleep 0.5 --workers 8
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Sector exclusion ────────────────────────────────────────────────────────

EXCLUDED_SECTORS: set[str] = {
    "Utilities",
    "Real Estate",
    "Consumer Defensive",   # yfinance name for Consumer Staples
    "Healthcare",           # yfinance name for Health Care
    "Financial Services",   # yfinance name for Financials
}

# ── NASDAQ trader file URLs ─────────────────────────────────────────────────

_NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_LISTED_URL  = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# Common stock symbol: 1-5 uppercase letters, optional hyphen + letter (e.g. BRK-B)
_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")


def _is_common_stock(symbol: str) -> bool:
    return bool(_SYMBOL_RE.match(symbol))


def _fetch_lines(url: str) -> list[str]:
    resp = requests.get(
        url, timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"},
    )
    resp.raise_for_status()
    return resp.text.strip().splitlines()


# ── Ticker list fetching ────────────────────────────────────────────────────

def fetch_all_tickers() -> list[str]:
    """Fetch all NASDAQ + NYSE common stock tickers from NASDAQ trader files."""
    tickers: set[str] = set()

    # NASDAQ-listed stocks
    # Columns: Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
    try:
        lines = _fetch_lines(_NASDAQ_LISTED_URL)
        for line in lines[1:]:
            if line.startswith("File Creation"):
                break
            parts = line.split("|")
            if len(parts) < 7:
                continue
            symbol     = parts[0].strip()
            test_issue = parts[3].strip()
            fin_status = parts[4].strip()
            etf        = parts[6].strip()
            if etf == "N" and test_issue == "N" and fin_status == "N" and _is_common_stock(symbol):
                tickers.add(symbol)
        logger.info("NASDAQ listed: %d tickers", len(tickers))
    except Exception as e:
        logger.error("Failed to fetch NASDAQ listed: %s", e)

    before = len(tickers)

    # Other exchanges (NYSE, AMEX)
    # Columns: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
    try:
        lines = _fetch_lines(_OTHER_LISTED_URL)
        for line in lines[1:]:
            if line.startswith("File Creation"):
                break
            parts = line.split("|")
            if len(parts) < 7:
                continue
            symbol     = parts[0].strip()
            exchange   = parts[2].strip()
            etf        = parts[4].strip()
            test_issue = parts[6].strip()
            # N=NYSE, A=NYSE American (AMEX)
            if exchange in ("N", "A") and etf == "N" and test_issue == "N" and _is_common_stock(symbol):
                tickers.add(symbol)
        logger.info("NYSE/AMEX added: +%d tickers (total %d)", len(tickers) - before, len(tickers))
    except Exception as e:
        logger.error("Failed to fetch other listed: %s", e)

    return sorted(tickers)


# ── Sector / name fetching via yfinance ────────────────────────────────────

def _fetch_one(ticker: str) -> dict:
    """Fetch sector and name for one ticker. Returns dict with defaults on error."""
    try:
        info = yf.Ticker(ticker).info
        return {
            "sector": info.get("sector") or "Unknown",
            "name":   info.get("longName") or info.get("shortName") or ticker,
        }
    except Exception:
        return {"sector": "Unknown", "name": ticker}


def fetch_sector_map(
    tickers: list[str],
    existing: dict[str, dict],
    max_workers: int = 8,
    sleep: float = 0.2,
) -> dict[str, dict]:
    """Fetch sector + name for tickers not already in existing map."""
    missing = [t for t in tickers if t not in existing]
    if not missing:
        logger.info("Sector map already complete for all tickers.")
        return existing

    logger.info("Fetching sector/name for %d tickers (workers=%d)...", len(missing), max_workers)
    result = dict(existing)

    def _worker(ticker: str) -> tuple[str, dict]:
        time.sleep(sleep)
        return ticker, _fetch_one(ticker)

    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, t): t for t in missing}
        for future in as_completed(futures):
            ticker, info = future.result()
            result[ticker] = info
            completed += 1
            if completed % 200 == 0:
                logger.info("  %d / %d done", completed, len(missing))

    return result


# ── Main build function ─────────────────────────────────────────────────────

def build_universe(
    universe_path: str = "stocks/universe.txt",
    sector_map_path: str = "stocks/sector_map.json",
    max_workers: int = 8,
    sleep: float = 0.2,
) -> None:
    os.makedirs("stocks", exist_ok=True)

    # 1. Fetch full ticker list
    logger.info("Fetching ticker list from NASDAQ trader files...")
    tickers = fetch_all_tickers()
    logger.info("Total common stocks: %d", len(tickers))

    # 2. Load existing sector map (incremental update)
    sector_map: dict[str, dict] = {}
    if os.path.exists(sector_map_path):
        with open(sector_map_path) as f:
            sector_map = json.load(f)
        logger.info("Loaded existing sector map: %d entries", len(sector_map))

    # 3. Fetch missing sector/name data
    sector_map = fetch_sector_map(tickers, sector_map, max_workers=max_workers, sleep=sleep)

    # 4. Save full sector map
    with open(sector_map_path, "w", encoding="utf-8") as f:
        json.dump(sector_map, f, ensure_ascii=False)
    logger.info("Sector map saved: %s (%d entries)", sector_map_path, len(sector_map))

    # 5. Apply sector filter
    filtered = [
        t for t in tickers
        if sector_map.get(t, {}).get("sector", "Unknown") not in EXCLUDED_SECTORS
    ]
    n_excluded = len(tickers) - len(filtered)

    with open(universe_path, "w") as f:
        f.write("\n".join(filtered))

    logger.info(
        "Universe: %d → %d tickers (%d excluded by sector filter: %s)",
        len(tickers), len(filtered), n_excluded,
        ", ".join(sorted(EXCLUDED_SECTORS)),
    )
    logger.info("Universe saved: %s", universe_path)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build NYSE+NASDAQ universe with sector filter")
    p.add_argument("--universe",    default="stocks/universe.txt")
    p.add_argument("--sector-map",  default="stocks/sector_map.json")
    p.add_argument("--workers",     type=int,   default=8,   help="Parallel workers for yfinance")
    p.add_argument("--sleep",       type=float, default=0.2, help="Sleep between requests (per worker)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    build_universe(
        universe_path=args.universe,
        sector_map_path=args.sector_map,
        max_workers=args.workers,
        sleep=args.sleep,
    )
