"""Data fetcher: OHLCV for US stocks.

Primary source:  Stooq (stooq.com) — no API key, no rate limits
Fallback source: yfinance — threads=False + exponential backoff on 429

Earnings calendar still uses yfinance (called for top-50 only).
"""

from __future__ import annotations

import logging
import time
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

logger = logging.getLogger(__name__)

_OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]

_STOOQ_URL = "https://stooq.com/q/d/l/?s={ticker}.us&d1={d1}&d2={d2}&i=d"


# ── Stooq (primary) ─────────────────────────────────────────────────────────

def _fetch_stooq_one(
    ticker: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame | None:
    """Fetch daily OHLCV from Stooq for one ticker. Returns None on failure."""
    url = _STOOQ_URL.format(
        ticker=ticker.lower(),
        d1=start.strftime("%Y%m%d"),
        d2=end.strftime("%Y%m%d"),
    )
    try:
        df = pd.read_csv(url, parse_dates=["Date"])

        # Stooq sometimes returns "No data" as a single-cell CSV
        if df.empty or df.columns[0].lower() not in ("date",):
            return None

        # Normalise column names (Stooq uses title-case)
        df = df.rename(columns={c: c.strip().title() for c in df.columns})
        missing = [c for c in _OHLCV_COLS if c not in df.columns]
        if missing:
            return None

        df = df.set_index("Date")[_OHLCV_COLS].dropna()
        df = df[df["Volume"] > 0]
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        return df.astype(float) if len(df) >= 60 else None
    except Exception:
        return None


def _fetch_stooq_batch(
    tickers: list[str],
    start: datetime,
    end: datetime,
    sleep: float = 0.15,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Fetch OHLCV for a list of tickers from Stooq.

    Returns (results, failed) where failed is a list of tickers to retry via yfinance.
    """
    results: dict[str, pd.DataFrame] = {}
    failed:  list[str] = []

    for ticker in tickers:
        df = _fetch_stooq_one(ticker, start, end)
        if df is not None:
            results[ticker] = df
        else:
            failed.append(ticker)
        time.sleep(sleep)

    return results, failed


# ── yfinance (fallback) ─────────────────────────────────────────────────────

def _fetch_yfinance_batch(
    tickers: list[str],
    start: datetime,
    end: datetime,
    max_retries: int = 3,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV from yfinance with retry on rate-limit errors.

    Uses threads=False to avoid burst requests when running in parallel jobs.
    """
    import yfinance as yf

    results: dict[str, pd.DataFrame] = {}

    for attempt in range(max_retries):
        try:
            raw = yf.download(
                tickers,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=False,          # sequential: avoids burst of parallel requests
            )
        except Exception as e:
            err = str(e)
            if "429" in err or "Too Many Requests" in err or "rate limit" in err.lower():
                wait = 30 * (2 ** attempt)   # 30 s → 60 s → 120 s
                logger.warning("yfinance rate-limited; waiting %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
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

        return results  # success

    logger.warning("yfinance: all %d retries exhausted for %d tickers", max_retries, len(tickers))
    return results


# ── Earnings calendar ────────────────────────────────────────────────────────

def fetch_upcoming_earnings(tickers: list[str], days_ahead: int = 5) -> dict[str, str]:
    """Fetch upcoming earnings dates via yfinance (called for top-50 candidates only)."""
    import yfinance as yf

    today  = datetime.now(ET).date()
    cutoff = today + timedelta(days=days_ahead)
    result: dict[str, str] = {}

    for ticker in tickers:
        for attempt in range(3):
            try:
                cal = yf.Ticker(ticker).calendar
                if cal is None:
                    break
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
                break
            except Exception as e:
                err = str(e)
                if "429" in err or "Too Many Requests" in err:
                    wait = 15 * (2 ** attempt)
                    logger.warning("Earnings fetch rate-limited; waiting %ds", wait)
                    time.sleep(wait)
                else:
                    break

    logger.info("Earnings calendar: %d stocks with upcoming announcements", len(result))
    return result


# ── Public API ───────────────────────────────────────────────────────────────

def fetch_all_ohlcv(
    tickers: list[str],
    days: int = 400,
    chunk_index: int | None = None,
    total_chunks: int | None = None,
    sleep_between: float = 1.0,
    batch_size: int = 50,
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for all tickers.

    Tries Stooq first (no rate limits); falls back to yfinance for missed tickers.
    """
    if chunk_index is not None and total_chunks is not None:
        size    = len(tickers) // total_chunks
        start_i = chunk_index * size
        end_i   = start_i + size if chunk_index < total_chunks - 1 else len(tickers)
        tickers = tickers[start_i:end_i]

    today = datetime.now(ET).replace(tzinfo=None)
    end   = today + timedelta(days=1)
    start = today - timedelta(days=days)

    results:  dict[str, pd.DataFrame] = {}
    yf_queue: list[str] = []
    total = len(tickers)

    # ── Pass 1: Stooq ────────────────────────────────────────────────────
    logger.info("Pass 1/2 — Stooq: fetching OHLCV for %d stocks...", total)
    for i in range(0, total, batch_size):
        batch = tickers[i: i + batch_size]
        ok, failed = _fetch_stooq_batch(batch, start, end)
        results.update(ok)
        yf_queue.extend(failed)
        logger.info(
            "  Stooq batch %d-%d: %d ok / %d failed (total ok: %d)",
            i + 1, min(i + batch_size, total),
            len(ok), len(failed), len(results),
        )
        if i + batch_size < total:
            time.sleep(sleep_between)

    # ── Pass 2: yfinance fallback for Stooq misses ───────────────────────
    if yf_queue:
        logger.info("Pass 2/2 — yfinance fallback: %d tickers not found on Stooq", len(yf_queue))
        for i in range(0, len(yf_queue), batch_size):
            batch = yf_queue[i: i + batch_size]
            ok = _fetch_yfinance_batch(batch, start, end)
            results.update(ok)
            logger.info(
                "  yfinance batch %d-%d: %d/%d fetched",
                i + 1, min(i + batch_size, len(yf_queue)),
                len(ok), len(batch),
            )
            if i + batch_size < len(yf_queue):
                time.sleep(sleep_between)

    logger.info(
        "Fetch complete: %d/%d stocks (Stooq: %d, yfinance fallback: %d, missing: %d)",
        len(results), total,
        len(results) - len([t for t in yf_queue if t in results]),
        len([t for t in yf_queue if t in results]),
        total - len(results),
    )
    return results
