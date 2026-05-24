"""Stock universe reader and metadata fetcher.

Primary source: stocks/universe.txt (NYSE + NASDAQ, sector-filtered).
Fallback:       S&P 500 from Wikipedia.
"""

import json
import logging
import os
import pandas as pd

logger = logging.getLogger(__name__)

# yfinance sector names for the sectors to exclude
EXCLUDED_SECTORS: set[str] = {
    "Utilities",
    "Real Estate",
    "Consumer Defensive",   # Consumer Staples in GICS
    "Healthcare",           # Health Care in GICS
    "Financial Services",   # Financials in GICS
}

_SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _fetch_sp500_from_wikipedia() -> pd.DataFrame:
    """Fetch S&P 500 component list from Wikipedia."""
    try:
        tables = pd.read_html(_SP500_WIKI_URL, header=0)
        df = tables[0]
        return df
    except Exception as e:
        logger.error("Failed to fetch S&P 500 from Wikipedia: %s", e)
        return pd.DataFrame()


def get_sp500_tickers(
    master_path: str = "stocks/sp500_info.csv",
    txt_cache: str = "stocks/sp500_tickers.txt",
) -> list[str]:
    """Return S&P 500 ticker symbols."""
    # Try text cache first
    if txt_cache and os.path.exists(txt_cache):
        with open(txt_cache) as f:
            tickers = [line.strip() for line in f if line.strip()]
        if tickers:
            logger.info("Loaded %d tickers from cache %s", len(tickers), txt_cache)
            return tickers

    # Try CSV master
    if master_path and os.path.exists(master_path):
        try:
            df = pd.read_csv(master_path, dtype=str)
            if "Symbol" in df.columns:
                tickers = df["Symbol"].dropna().str.strip().tolist()
                tickers = [t.replace(".", "-") for t in tickers]
                if tickers:
                    _save_txt_cache(tickers, txt_cache)
                    logger.info("Loaded %d tickers from %s", len(tickers), master_path)
                    return tickers
        except Exception as e:
            logger.warning("Failed to read master CSV: %s", e)

    # Fetch from Wikipedia
    logger.info("Fetching S&P 500 list from Wikipedia...")
    df = _fetch_sp500_from_wikipedia()
    if df.empty:
        logger.warning("No S&P 500 data; returning empty list.")
        return []

    tickers = df["Symbol"].dropna().astype(str).str.strip().tolist()
    tickers = [t.replace(".", "-") for t in tickers]  # BRK.B → BRK-B for yfinance

    # Save CSV master
    if master_path:
        os.makedirs(os.path.dirname(master_path) or ".", exist_ok=True)
        df.to_csv(master_path, index=False)
        logger.info("Saved S&P 500 master to %s", master_path)

    _save_txt_cache(tickers, txt_cache)
    logger.info("Found %d S&P 500 stocks.", len(tickers))
    return tickers


def _save_txt_cache(tickers: list[str], txt_cache: str) -> None:
    if not txt_cache:
        return
    os.makedirs(os.path.dirname(txt_cache) or ".", exist_ok=True)
    with open(txt_cache, "w") as f:
        f.write("\n".join(tickers))
    logger.info("Saved %d tickers to %s", len(tickers), txt_cache)


def get_stock_info(master_path: str = "stocks/sp500_info.csv") -> dict[str, dict]:
    """Return dict mapping ticker → {name, sector, sub_sector}."""
    # Try CSV master
    if master_path and os.path.exists(master_path):
        try:
            df = pd.read_csv(master_path, dtype=str)
            return _df_to_info(df)
        except Exception as e:
            logger.warning("Failed to read master CSV for info: %s", e)

    # Fetch from Wikipedia
    logger.info("Fetching S&P 500 info from Wikipedia...")
    df = _fetch_sp500_from_wikipedia()
    if df.empty:
        return {}

    # Save for future use
    if master_path:
        os.makedirs(os.path.dirname(master_path) or ".", exist_ok=True)
        df.to_csv(master_path, index=False)

    return _df_to_info(df)


def get_universe_tickers(
    universe_path: str = "stocks/universe.txt",
    master_path: str = "stocks/sp500_info.csv",
    txt_cache: str = "stocks/sp500_tickers.txt",
) -> list[str]:
    """Return universe tickers (NYSE + NASDAQ, sector-filtered).

    Falls back to S&P 500 if stocks/universe.txt has not been built yet.
    Run scanner/build_universe.py (or the refresh-universe workflow) to build it.
    """
    if os.path.exists(universe_path):
        with open(universe_path) as f:
            tickers = [line.strip() for line in f if line.strip()]
        if tickers:
            logger.info("Loaded %d tickers from universe %s", len(tickers), universe_path)
            return tickers

    logger.warning(
        "%s not found — falling back to S&P 500. "
        "Run scanner/build_universe.py to build the full universe.",
        universe_path,
    )
    return get_sp500_tickers(master_path, txt_cache)


def get_universe_info(
    sector_map_path: str = "stocks/sector_map.json",
    master_path: str = "stocks/sp500_info.csv",
) -> dict[str, dict]:
    """Return {ticker: {name, sector, sub_sector}} from sector_map or S&P 500 CSV."""
    # Try sector_map.json first (covers full NYSE + NASDAQ universe)
    if os.path.exists(sector_map_path):
        try:
            with open(sector_map_path, encoding="utf-8") as f:
                raw: dict[str, dict] = json.load(f)
            info = {
                ticker: {
                    "name":       entry.get("name", ticker),
                    "sector":     entry.get("sector", ""),
                    "sub_sector": "",
                }
                for ticker, entry in raw.items()
            }
            logger.info("Loaded info for %d tickers from %s", len(info), sector_map_path)
            return info
        except Exception as e:
            logger.warning("Failed to read sector map: %s", e)

    # Fall back to S&P 500 CSV
    return get_stock_info(master_path)


def _df_to_info(df: pd.DataFrame) -> dict[str, dict]:
    """Convert S&P 500 Wikipedia DataFrame to info dict."""
    info: dict[str, dict] = {}
    for _, row in df.iterrows():
        symbol = str(row.get("Symbol", "")).strip().replace(".", "-")
        if not symbol:
            continue
        info[symbol] = {
            "name":       str(row.get("Security", symbol)),
            "sector":     str(row.get("GICS Sector", "")),
            "sub_sector": str(row.get("GICS Sub-Industry", "")),
        }
    return info
