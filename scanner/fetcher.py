"""Data fetcher: yfinance batch download for US stocks."""

from __future__ import annotations

import logging
import time
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)

_OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]


# ── yfinance batch download ─────────────────────────────────────────────

def _fetch_yfinance_batch(
    tickers: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    results: dict[str, pd.DataFrame] = {}

    try:
        raw = yf.download(
            tickers,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        logger.warning("yfinance batch download failed: %s", e)
        return results

    if raw is None or raw.empty:
        return results

    for ticker in tickers:
        try:
            df = raw[ticker].copy() if len(tickers) > 1 else raw.copy()
            df = df[_OHLCV_COLS].dropna()
            df = df[df["Volume"] > 0]
            df.index = pd.to_datetime(df.index)
            if len(df) >= 60:
                results[ticker] = df.astype(float)
        except Exception:
            pass

    return results


# ── Earnings calendar ────────────────────────────────────────────────────

def fetch_upcoming_earnings(tickers: list[str], days_ahead: int = 5) -> dict[str, str]:
    """Fetch upcoming earnings dates for a list of US stock tickers via yfinance.

    Returns {ticker: date_str} for stocks announcing within days_ahead days from today.
    Called after scanning so only candidate tickers are queried.
    """
    import yfinance as yf

    today = datetime.now(ET).date()
    cutoff = today + timedelta(days=days_ahead)
    result: dict[str, str] = {}

    for ticker in tickers:
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None:
                continue
            if isinstance(cal, dict):
                earn_dates = cal.get("Earnings Date", [])
                if not hasattr(earn_dates, "__iter__") or isinstance(earn_dates, str):
                    earn_dates = [earn_dates]
                for earn_date in earn_dates:
                    if hasattr(earn_date, "date"):
                        earn_date = earn_date.date()
                    elif isinstance(earn_date, str):
                        try:
                            earn_date = datetime.strptime(earn_date[:10], "%Y-%m-%d").date()
                        except Exception:
                            continue
                    if today <= earn_date <= cutoff:
                        result[ticker] = earn_date.strftime("%Y-%m-%d")
                        break
        except Exception:
            pass

    logger.info("Earnings calendar: %d stocks with upcoming announcements", len(result))
    return result


# ── Public API ───────────────────────────────────────────────────────────

def fetch_all_ohlcv(
    tickers: list[str],
    days: int = 400,
    chunk_index: int | None = None,
    total_chunks: int | None = None,
    sleep_between: float = 0.5,
    batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    if chunk_index is not None and total_chunks is not None:
        size    = len(tickers) // total_chunks
        start_i = chunk_index * size
        end_i   = start_i + size if chunk_index < total_chunks - 1 else len(tickers)
        tickers = tickers[start_i:end_i]

    today = datetime.now(ET).replace(tzinfo=None)
    end   = today + timedelta(days=1)
    start = today - timedelta(days=days)

    results: dict[str, pd.DataFrame] = {}
    total = len(tickers)

    logger.info("Fetching OHLCV for %d US stocks via yfinance...", total)
    for i in range(0, total, batch_size):
        batch = tickers[i: i + batch_size]
        batch_results = _fetch_yfinance_batch(batch, start, end)
        results.update(batch_results)
        logger.info(
            "  Batch %d-%d: %d/%d fetched (total so far: %d)",
            i + 1, min(i + batch_size, total),
            len(batch_results), len(batch),
            len(results),
        )
        if i + batch_size < total:
            time.sleep(sleep_between)

    logger.info(
        "Fetch complete: %d/%d stocks successfully retrieved.",
        len(results), total,
    )
    return results
