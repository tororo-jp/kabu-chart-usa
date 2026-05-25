"""Build NYSE + NASDAQ universe with sector filtering.

Sector data sources (in priority order):
  1. GitHub raw CSV     — S&P 500 GICS sectors, reliable plain CSV, always accessible
  2. Wikipedia          — S&P 500/400/600, GICS sector, used as override/fallback
  3. NASDAQ Screener CSV— all NYSE+NASDAQ stocks, single request (may return 403)

yfinance is NOT used for sector data (avoids rate limiting).

Output:
  stocks/sector_map.json  — {ticker: {sector, name}} for all known tickers
  stocks/universe.txt     — filtered ticker list (excluded sectors removed)

Run:
  python scanner/build_universe.py
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re

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
    "Consumer Defensive",   # Consumer Staples in GICS
    "Healthcare",           # Health Care in GICS
    "Financial Services",   # Financials in GICS
}

# NASDAQ Screener sector names → normalised yfinance-style names
_NASDAQ_TO_NORM: dict[str, str] = {
    # GICS-aligned (newer screener format)
    "Technology":                 "Technology",
    "Health Care":                "Healthcare",
    "Financials":                 "Financial Services",
    "Financial Services":         "Financial Services",
    "Consumer Discretionary":     "Consumer Cyclical",
    "Consumer Staples":           "Consumer Defensive",
    "Energy":                     "Energy",
    "Utilities":                  "Utilities",
    "Real Estate":                "Real Estate",
    "Industrials":                "Industrials",
    "Materials":                  "Basic Materials",
    "Communication Services":     "Communication Services",
    # Legacy NASDAQ categories
    "Finance":                    "Financial Services",
    "Consumer Services":          "Consumer Cyclical",
    "Consumer Non-Durables":      "Consumer Defensive",
    "Consumer Durables":          "Consumer Cyclical",
    "Capital Goods":              "Industrials",
    "Basic Industries":           "Basic Materials",
    "Transportation":             "Industrials",
    "Public Utilities":           "Utilities",
    "Real Estate & Construction": "Real Estate",
    "Miscellaneous":              "Unknown",
}

# GICS names (Wikipedia) → normalised names
_GICS_TO_NORM: dict[str, str] = {
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

# ── NASDAQ trader file URLs ─────────────────────────────────────────────────

_NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER_LISTED_URL  = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# GitHub datasets — plain CSV, no auth, always accessible
_GITHUB_SP500_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
    "/main/data/constituents.csv"
)

# NASDAQ screener — try multiple URL variants for resilience (may return 403)
_SCREENER_URLS = [
    "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true",
    "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&offset=0&download=true",
]

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer":         "https://www.nasdaq.com/",
}

_WIKI_URLS = {
    "S&P 500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "S&P 400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "S&P 600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}

_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")


def _is_common_stock(symbol: str) -> bool:
    return bool(_SYMBOL_RE.match(symbol))


# ── Step 1: Full ticker list ────────────────────────────────────────────────

def fetch_all_tickers() -> list[str]:
    """Fetch all NASDAQ + NYSE common stock tickers from NASDAQ trader files."""
    tickers: set[str] = set()

    def _parse_line_nasdaq(line: str) -> str | None:
        parts = line.split("|")
        if len(parts) < 7:
            return None
        sym, test, fin, etf = parts[0].strip(), parts[3].strip(), parts[4].strip(), parts[6].strip()
        return sym if etf == "N" and test == "N" and fin == "N" and _is_common_stock(sym) else None

    def _parse_line_other(line: str) -> str | None:
        parts = line.split("|")
        if len(parts) < 7:
            return None
        sym, exch, etf, test = parts[0].strip(), parts[2].strip(), parts[4].strip(), parts[6].strip()
        return sym if exch in ("N", "A") and etf == "N" and test == "N" and _is_common_stock(sym) else None

    for url, parser, label in [
        (_NASDAQ_LISTED_URL, _parse_line_nasdaq, "NASDAQ"),
        (_OTHER_LISTED_URL,  _parse_line_other,  "NYSE/AMEX"),
    ]:
        try:
            resp = requests.get(url, timeout=30, headers=_HEADERS)
            resp.raise_for_status()
            before = len(tickers)
            for line in resp.text.strip().splitlines()[1:]:
                if line.startswith("File Creation"):
                    break
                sym = parser(line)
                if sym:
                    tickers.add(sym)
            logger.info("%s: +%d tickers (total %d)", label, len(tickers) - before, len(tickers))
        except Exception as e:
            logger.error("Failed to fetch %s tickers: %s", label, e)

    return sorted(tickers)


# ── Step 2a: Sector map from NASDAQ Screener CSV ────────────────────────────

def fetch_nasdaq_screener() -> dict[str, dict]:
    """Fetch sector + name for all NYSE+NASDAQ stocks from NASDAQ Screener CSV.

    Returns {ticker: {sector, name}} with normalised sector names.
    Returns empty dict on failure (caller should fall back to Wikipedia).
    """
    for url in _SCREENER_URLS:
        try:
            resp = requests.get(url, timeout=60, headers=_HEADERS)
            resp.raise_for_status()

            # The CSV may have a trailing summary row ("XXX total nasdaq listed...")
            # Read with pandas, skip non-data rows
            raw = resp.text
            df = pd.read_csv(io.StringIO(raw), dtype=str)

            # Normalise column names (case-insensitive)
            df.columns = [c.strip().lower() for c in df.columns]

            sym_col    = next((c for c in df.columns if c == "symbol"),    None)
            name_col   = next((c for c in df.columns if c == "name"),      None)
            sector_col = next((c for c in df.columns if c == "sector"),    None)

            if sym_col is None or sector_col is None:
                logger.warning("NASDAQ screener: unexpected columns: %s", list(df.columns))
                continue

            result: dict[str, dict] = {}
            for _, row in df.iterrows():
                sym = str(row.get(sym_col, "")).strip().replace(".", "-")
                if not sym or sym.lower() == "nan" or not _is_common_stock(sym):
                    continue
                raw_sector = str(row.get(sector_col, "")).strip()
                name       = str(row.get(name_col, sym)).strip() if name_col else sym
                sector     = _NASDAQ_TO_NORM.get(raw_sector, raw_sector or "Unknown")
                result[sym] = {"sector": sector, "name": name}

            # Log unique sector names found (helps diagnose mapping gaps)
            unique_raw = {str(row.get(sector_col, "")).strip() for _, row in df.iterrows()}
            unmapped   = unique_raw - set(_NASDAQ_TO_NORM) - {"", "nan"}
            if unmapped:
                logger.warning("Unmapped NASDAQ sector names (will pass through): %s", sorted(unmapped))

            logger.info("NASDAQ screener: %d tickers with sector data", len(result))
            return result

        except Exception as e:
            logger.warning("NASDAQ screener fetch failed (%s): %s", url, e)

    logger.warning("All NASDAQ screener URLs failed — will rely on other sources.")
    return {}


# ── Step 2b: Sector map from GitHub raw CSV (S&P 500) ───────────────────────

def fetch_github_sp500() -> dict[str, dict]:
    """Fetch S&P 500 sector data from GitHub datasets public CSV.

    URL never requires auth and returns plain CSV — the most reliable source.
    Columns: Symbol, Security, GICS Sector, GICS Sub-Industry, ...
    """
    try:
        df = pd.read_csv(_GITHUB_SP500_URL, dtype=str)
        df.columns = [c.strip() for c in df.columns]

        sym_col  = next((c for c in df.columns if c.lower() in ("symbol", "ticker")), None)
        name_col = next((c for c in df.columns if "security" in c.lower() or c.lower() == "name"), None)
        sect_col = next((c for c in df.columns if "gics sector" in c.lower()), None)
        if sect_col is None:
            sect_col = next((c for c in df.columns if c.lower() == "sector"), None)
        sub_col  = next((c for c in df.columns if "sub-industry" in c.lower() or "sub_industry" in c.lower()), None)

        if sym_col is None or sect_col is None:
            logger.warning("GitHub S&P 500 CSV: unexpected columns: %s", list(df.columns))
            return {}

        result: dict[str, dict] = {}
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip().replace(".", "-")
            if not sym or sym == "nan" or not _is_common_stock(sym):
                continue
            gics   = str(row[sect_col]).strip()
            sector = _GICS_TO_NORM.get(gics, gics or "Unknown")
            name   = str(row[name_col]).strip() if name_col else sym
            sub    = str(row[sub_col]).strip() if sub_col else ""
            result[sym] = {"sector": sector, "name": name, "sub_sector": sub}

        logger.info("GitHub S&P 500 CSV: %d tickers with sector data", len(result))
        return result
    except Exception as e:
        logger.warning("GitHub S&P 500 CSV fetch failed: %s", e)
        return {}


# ── Step 2c: Sector map from Wikipedia (S&P 1500) ───────────────────────────

def fetch_wikipedia_sectors() -> dict[str, dict]:
    """Fetch sector + name for S&P 500/400/600 from Wikipedia.

    Used as an override on top of other sector data (GICS is more precise).
    S&P 500 uses "Symbol" column; S&P 400/600 use "Ticker" column.
    """
    result: dict[str, dict] = {}

    for index_name, url in _WIKI_URLS.items():
        try:
            tables = pd.read_html(url, header=0)
            matched = False
            for table_idx, df in enumerate(tables[:4]):
                sym_col = next(
                    (c for c in df.columns if c.lower() in ("symbol", "ticker")), None
                )
                if sym_col is None:
                    continue
                name_col = next(
                    (c for c in df.columns if "security" in c.lower() or "company" in c.lower() or "name" in c.lower()),
                    None,
                )
                sect_col = next((c for c in df.columns if "sector" in c.lower()), None)

                before = len(result)
                for _, row in df.iterrows():
                    sym = str(row[sym_col]).strip().replace(".", "-")
                    if not sym or sym == "nan":
                        continue
                    gics   = str(row[sect_col]).strip() if sect_col else ""
                    sector = _GICS_TO_NORM.get(gics, gics or "Unknown")
                    name   = str(row[name_col]).strip() if name_col else sym
                    result[sym] = {"sector": sector, "name": name}

                logger.info(
                    "Wikipedia %s (table %d): +%d tickers (total %d)",
                    index_name, table_idx, len(result) - before, len(result),
                )
                matched = True
                break

            if not matched:
                logger.warning("Wikipedia %s: symbol/ticker column not found in first 4 tables", index_name)
        except Exception as e:
            logger.warning("Wikipedia %s fetch failed: %s", index_name, e)

    logger.info("Wikipedia total: %d tickers", len(result))
    return result


# ── Main build function ─────────────────────────────────────────────────────

def build_universe(
    universe_path: str = "stocks/universe.txt",
    sector_map_path: str = "stocks/sector_map.json",
) -> None:
    os.makedirs("stocks", exist_ok=True)

    # 1. Full ticker list
    logger.info("Fetching ticker list from NASDAQ trader files...")
    tickers = fetch_all_tickers()
    logger.info("Total common stocks: %d", len(tickers))

    # 2. Load existing sector map (preserve previous data)
    sector_map: dict[str, dict] = {}
    if os.path.exists(sector_map_path):
        with open(sector_map_path, encoding="utf-8") as f:
            sector_map = json.load(f)
        logger.info("Loaded existing sector map: %d entries", len(sector_map))

    # 3. NASDAQ screener — broad coverage (may return 403; best-effort)
    logger.info("Fetching sector data from NASDAQ screener (best-effort)...")
    screener_data = fetch_nasdaq_screener()
    sector_map.update(screener_data)

    # 4. GitHub raw CSV — reliable S&P 500 GICS data (plain CSV, always accessible)
    logger.info("Fetching sector data from GitHub S&P 500 CSV...")
    github_data = fetch_github_sp500()
    sector_map.update(github_data)   # overrides screener with GICS-precise data

    # 5. Wikipedia — override with precise GICS data for S&P 400/600
    logger.info("Fetching sector data from Wikipedia (S&P 1500)...")
    wiki_data = fetch_wikipedia_sectors()
    sector_map.update(wiki_data)   # Wikipedia takes precedence over screener

    # 6. Coverage report
    covered   = sum(1 for t in tickers if t in sector_map)
    uncovered = len(tickers) - covered
    logger.info(
        "Coverage: %d / %d tickers have sector data (%d unknown → included by default)",
        covered, len(tickers), uncovered,
    )

    # 7. Save sector map
    with open(sector_map_path, "w", encoding="utf-8") as f:
        json.dump(sector_map, f, ensure_ascii=False)
    logger.info("Sector map saved: %s", sector_map_path)

    # 8. Apply sector filter
    # Unknown sector (no data) → included by default
    filtered  = [
        t for t in tickers
        if sector_map.get(t, {}).get("sector", "Unknown") not in EXCLUDED_SECTORS
    ]
    n_excluded = len(tickers) - len(filtered)

    with open(universe_path, "w") as f:
        f.write("\n".join(filtered))

    logger.info(
        "Universe: %d → %d tickers (%d excluded: %s)",
        len(tickers), len(filtered), n_excluded,
        ", ".join(sorted(EXCLUDED_SECTORS)),
    )
    logger.info("Universe saved: %s", universe_path)


# ── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build NYSE+NASDAQ universe with sector filter")
    p.add_argument("--universe",   default="stocks/universe.txt")
    p.add_argument("--sector-map", default="stocks/sector_map.json")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    build_universe(universe_path=args.universe, sector_map_path=args.sector_map)
