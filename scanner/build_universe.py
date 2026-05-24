"""Build NYSE + NASDAQ universe with sector filtering.

Sector data priority:
  1. Wikipedia — S&P 500 / S&P 400 / S&P 600 (rate-limit-free, covers ~1,500 tickers)
  2. yfinance   — remaining tickers only, single-threaded with backoff (optional)
     Pass --with-yfinance to enable. Skipped by default to avoid rate limits.

Non-S&P-1500 tickers with no sector data are INCLUDED by default (sector = "Unknown").

Output:
  stocks/sector_map.json  — {ticker: {sector, name}} for all known tickers
  stocks/universe.txt     — filtered ticker list (excluded sectors removed)

Run:
  python scanner/build_universe.py                   # Wikipedia only (fast, safe)
  python scanner/build_universe.py --with-yfinance   # + yfinance for non-S&P-1500
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time

import pandas as pd
import requests

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

# GICS names (Wikipedia) → yfinance sector names
_GICS_TO_YF: dict[str, str] = {
    "Health Care":            "Healthcare",
    "Financials":             "Financial Services",
    "Information Technology": "Technology",
    "Consumer Staples":       "Consumer Defensive",
    "Consumer Discretionary": "Consumer Cyclical",
    "Materials":              "Basic Materials",
    "Energy":                 "Energy",
    "Industrials":            "Industrials",
    "Communication Services": "Communication Services",
    "Utilities":              "Utilities",
    "Real Estate":            "Real Estate",
}

# ── Wikipedia S&P index URLs ────────────────────────────────────────────────

_WIKI_URLS = {
    "S&P 500":  "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "S&P 400":  "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "S&P 600":  "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}

# ── NASDAQ trader file URLs ─────────────────────────────────────────────────

_NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_LISTED_URL  = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

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


# ── Step 1: Full ticker list from NASDAQ trader files ──────────────────────

def fetch_all_tickers() -> list[str]:
    """Fetch all NASDAQ + NYSE common stock tickers from NASDAQ trader files."""
    tickers: set[str] = set()

    # NASDAQ: Symbol|Name|Market|Test|FinStatus|LotSize|ETF|NextShares
    try:
        for line in _fetch_lines(_NASDAQ_LISTED_URL)[1:]:
            if line.startswith("File Creation"):
                break
            parts = line.split("|")
            if len(parts) < 7:
                continue
            sym, test, fin, etf = parts[0].strip(), parts[3].strip(), parts[4].strip(), parts[6].strip()
            if etf == "N" and test == "N" and fin == "N" and _is_common_stock(sym):
                tickers.add(sym)
        logger.info("NASDAQ listed: %d tickers", len(tickers))
    except Exception as e:
        logger.error("Failed to fetch NASDAQ listed: %s", e)

    before = len(tickers)

    # Other: ActSymbol|Name|Exchange|CQS|ETF|LotSize|Test|NASDAQSymbol
    try:
        for line in _fetch_lines(_OTHER_LISTED_URL)[1:]:
            if line.startswith("File Creation"):
                break
            parts = line.split("|")
            if len(parts) < 7:
                continue
            sym, exch, etf, test = parts[0].strip(), parts[2].strip(), parts[4].strip(), parts[6].strip()
            if exch in ("N", "A") and etf == "N" and test == "N" and _is_common_stock(sym):
                tickers.add(sym)
        logger.info("NYSE/AMEX added: +%d tickers (total %d)", len(tickers) - before, len(tickers))
    except Exception as e:
        logger.error("Failed to fetch other listed: %s", e)

    return sorted(tickers)


# ── Step 2: Sector map from Wikipedia (S&P 1500) ───────────────────────────

def fetch_wikipedia_sectors() -> dict[str, dict]:
    """Fetch sector + name for S&P 500 / 400 / 600 from Wikipedia. No rate limits."""
    result: dict[str, dict] = {}

    for index_name, url in _WIKI_URLS.items():
        try:
            tables = pd.read_html(url, header=0)
            df = tables[0]

            # Column names differ slightly across pages; normalise
            sym_col    = next((c for c in df.columns if "symbol" in c.lower()), None)
            name_col   = next((c for c in df.columns if "security" in c.lower() or "company" in c.lower()), None)
            sector_col = next((c for c in df.columns if "sector" in c.lower()), None)

            if sym_col is None:
                logger.warning("%s: could not find symbol column", index_name)
                continue

            for _, row in df.iterrows():
                sym = str(row[sym_col]).strip().replace(".", "-")
                if not sym or sym == "nan":
                    continue

                gics_sector = str(row[sector_col]).strip() if sector_col else ""
                yf_sector   = _GICS_TO_YF.get(gics_sector, gics_sector or "Unknown")
                name        = str(row[name_col]).strip() if name_col else sym

                result[sym] = {"sector": yf_sector, "name": name}

            logger.info("Wikipedia %s: %d tickers", index_name, len(result))
        except Exception as e:
            logger.warning("Failed to fetch Wikipedia %s: %s", index_name, e)

    logger.info("Wikipedia total: %d tickers with sector data", len(result))
    return result


# ── Step 3: yfinance fallback for non-S&P-1500 (optional) ─────────────────

def _fetch_yf_one(ticker: str, session: requests.Session) -> dict:
    """Fetch sector + name via yfinance with retry on 429."""
    import yfinance as yf

    for attempt in range(4):
        try:
            info = yf.Ticker(ticker).info
            return {
                "sector": info.get("sector") or "Unknown",
                "name":   info.get("longName") or info.get("shortName") or ticker,
            }
        except Exception as exc:
            err = str(exc)
            if "429" in err or "Too Many Requests" in err:
                wait = 60 * (2 ** attempt)  # 60s → 120s → 240s → 480s
                logger.warning("Rate limited on %s; waiting %ds (attempt %d)", ticker, wait, attempt + 1)
                time.sleep(wait)
            else:
                break
    return {"sector": "Unknown", "name": ticker}


def fetch_yfinance_sectors(
    tickers: list[str],
    existing: dict[str, dict],
    sector_map_path: str,
    sleep: float = 2.0,
) -> dict[str, dict]:
    """Single-threaded yfinance sector fetch with conservative rate limiting."""
    missing = [t for t in tickers if t not in existing]
    if not missing:
        return existing

    logger.info(
        "yfinance sector fetch: %d tickers (single-threaded, %.1fs sleep). "
        "Est. time: ~%.0f min",
        len(missing), sleep, len(missing) * sleep / 60,
    )

    result = dict(existing)
    session = requests.Session()

    for i, ticker in enumerate(missing):
        result[ticker] = _fetch_yf_one(ticker, session)
        time.sleep(sleep)

        if (i + 1) % 500 == 0:
            logger.info("  %d / %d done — saving checkpoint", i + 1, len(missing))
            with open(sector_map_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)

    return result


# ── Main build function ─────────────────────────────────────────────────────

def build_universe(
    universe_path: str = "stocks/universe.txt",
    sector_map_path: str = "stocks/sector_map.json",
    with_yfinance: bool = False,
    yf_sleep: float = 2.0,
) -> None:
    os.makedirs("stocks", exist_ok=True)

    # 1. Full ticker list
    logger.info("Fetching ticker list from NASDAQ trader files...")
    tickers = fetch_all_tickers()
    logger.info("Total common stocks: %d", len(tickers))

    # 2. Load existing sector map
    sector_map: dict[str, dict] = {}
    if os.path.exists(sector_map_path):
        with open(sector_map_path, encoding="utf-8") as f:
            sector_map = json.load(f)
        logger.info("Loaded existing sector map: %d entries", len(sector_map))

    # 3. Wikipedia sectors for S&P 1500 (always; no rate limits)
    wiki = fetch_wikipedia_sectors()
    sector_map.update(wiki)  # Wikipedia overwrites stale yfinance data

    # 4. yfinance for non-S&P-1500 (optional; slow but comprehensive)
    if with_yfinance:
        non_sp1500 = [t for t in tickers if t not in sector_map]
        logger.info("%d tickers outside S&P 1500 — fetching via yfinance...", len(non_sp1500))
        sector_map = fetch_yfinance_sectors(non_sp1500, sector_map, sector_map_path, yf_sleep)
    else:
        unresolved = sum(1 for t in tickers if t not in sector_map)
        if unresolved:
            logger.info(
                "%d non-S&P-1500 tickers have no sector data → included by default. "
                "Re-run with --with-yfinance for full coverage.",
                unresolved,
            )

    # 5. Save sector map
    with open(sector_map_path, "w", encoding="utf-8") as f:
        json.dump(sector_map, f, ensure_ascii=False)
    logger.info("Sector map saved: %s (%d entries)", sector_map_path, len(sector_map))

    # 6. Apply sector filter
    # Tickers with no sector data (non-S&P-1500, unknown) are INCLUDED
    filtered = [
        t for t in tickers
        if sector_map.get(t, {}).get("sector", "Unknown") not in EXCLUDED_SECTORS
    ]
    n_excluded = len(tickers) - len(filtered)

    with open(universe_path, "w") as f:
        f.write("\n".join(filtered))

    logger.info(
        "Universe: %d → %d tickers (%d excluded by sector filter)",
        len(tickers), len(filtered), n_excluded,
    )
    logger.info("Universe saved: %s", universe_path)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build NYSE+NASDAQ universe with sector filter")
    p.add_argument("--universe",      default="stocks/universe.txt")
    p.add_argument("--sector-map",    default="stocks/sector_map.json")
    p.add_argument("--with-yfinance", action="store_true",
                   help="Also fetch sector via yfinance for non-S&P-1500 tickers (slow, ~2h)")
    p.add_argument("--yf-sleep",      type=float, default=2.0,
                   help="Sleep between yfinance calls in seconds (default: 2.0)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    build_universe(
        universe_path=args.universe,
        sector_map_path=args.sector_map,
        with_yfinance=args.with_yfinance,
        yf_sleep=args.yf_sleep,
    )
