"""Main scanner entrypoint — US stocks (S&P 500)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from fetcher import fetch_all_ohlcv, fetch_upcoming_earnings
from market_filter import check_market_env
from indicators import compute_all, compute_12m_return, blue_sky_check
from master import get_universe_tickers, get_universe_info
from patterns import detect_all_patterns
from scorer import calculate_score, calculate_probability
from target_calculator import calculate_targets


def _json_safe(v):
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return round(float(v), 2)
    if isinstance(v, float):
        return round(v, 2)
    return v


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="docs/data/results.json")
    p.add_argument("--master", default="stocks/sp500_info.csv")
    p.add_argument("--chunk", type=int, default=None)
    p.add_argument("--total-chunks", type=int, default=None)
    p.add_argument("--min-score", type=int, default=30)
    return p.parse_args()


def build_ohlcv_list(df: pd.DataFrame) -> list[dict]:
    rows = []
    for ts, row in df.iterrows():
        rows.append({
            "t": int(ts.timestamp()),
            "o": float(row["Open"]),
            "h": float(row["High"]),
            "l": float(row["Low"]),
            "c": float(row["Close"]),
            "v": int(row["Volume"]),
        })
    return rows[-120:]


def scan_stock(
    ticker: str,
    raw_df: pd.DataFrame,
    rs: float,
    info: dict,
) -> dict | None:
    try:
        df = compute_all(raw_df)
    except Exception as e:
        logger.debug("Indicator calc failed for %s: %s", ticker, e)
        return None

    patterns = detect_all_patterns(df)
    sky_info = blue_sky_check(df)
    total_score, score_breakdown = calculate_score(df, patterns, rs, sky_info)
    probability = calculate_probability(total_score, patterns, rs)
    current_price = float(df["Close"].iloc[-1])
    targets = calculate_targets(df, patterns, current_price)

    def safe(col):
        if col in df.columns and not pd.isna(df[col].iloc[-1]):
            return round(float(df[col].iloc[-1]), 2)
        return None

    indicators_snap = {
        "rsi":         safe("RSI_14"),
        "macd":        safe("MACD"),
        "macd_signal": safe("MACD_signal"),
        "sma5":        safe("SMA_5"),
        "sma25":       safe("SMA_25"),
        "sma75":       safe("SMA_75"),
        "sma200":      safe("SMA_200"),
        "bb_upper":    safe("BB_upper"),
        "bb_lower":    safe("BB_lower"),
        "atr":         safe("ATR_14"),
        "adx":         safe("ADX"),
        "vol_ratio": round(
            float(df["Volume"].iloc[-1] / df["VOL_MA_20"].iloc[-1])
            if "VOL_MA_20" in df.columns and df["VOL_MA_20"].iloc[-1] > 0
            else 1.0,
            2,
        ),
        "avg_daily_value": round(
            float(df["VOL_MA_20"].iloc[-1] * df["Close"].iloc[-1]) / 1_000_000
            if "VOL_MA_20" in df.columns and df["VOL_MA_20"].iloc[-1] > 0
            else 0,
            1,
        ),  # Unit: million USD
    }

    # Liquidity warning: < $1M/day average is illiquid for swing trading
    avg_dv_m = indicators_snap.get("avg_daily_value", 0) or 0
    liquidity_warning = avg_dv_m < 1.0

    return {
        "code":            ticker,
        "name":            info.get("name", ticker),
        "sector":          info.get("sector", ""),
        "sub_sector":      info.get("sub_sector", ""),
        "score":           total_score,
        "score_breakdown": score_breakdown,
        "probability":     probability,
        "rs":              round(rs, 1),
        "price":           current_price,
        "target":          round(targets.get("main_target", current_price), 2),
        "stop_loss":       round(targets["stop_loss"], 2),
        "rr_ratio":        targets["rr_ratio"],
        "target_basis":    targets.get("target_basis", "atr3"),
        "weeks_min":       targets.get("weeks_min", 2),
        "weeks_max":       targets.get("weeks_max", 4),
        "patterns": [
            {
                "name":       p.name,
                "label":      p.label,
                "confidence": round(p.confidence, 2),
                "details":    {k: _json_safe(v) for k, v in p.details.items()},
            }
            for p in patterns
        ],
        "indicators":        indicators_snap,
        "ohlcv":             build_ohlcv_list(df),
        "scan_date":         datetime.now(ET).strftime("%Y-%m-%d"),
        "liquidity_warning": liquidity_warning,
        "blue_sky":          sky_info.get("blue_sky", False),
        "at_52w_high":       sky_info.get("at_52w_high", False),
        "sky_years":         sky_info.get("sky_years", 0.0),
    }


def main():
    args = parse_args()
    sample_mode = os.environ.get("SAMPLE_MODE", "false").lower() == "true"

    tickers = get_universe_tickers(
        universe_path="stocks/universe.txt",
        master_path=args.master,
        txt_cache="stocks/sp500_tickers.txt",
    )
    if not tickers:
        logger.error("No tickers found. Run scanner/build_universe.py or check sp500_info.csv.")
        sys.exit(1)

    if sample_mode:
        tickers = tickers[:100]
        logger.info("Sample mode: using first %d tickers", len(tickers))

    stock_info = get_universe_info(
        sector_map_path="stocks/sector_map.json",
        master_path=args.master,
    )

    logger.info("Checking market environment...")
    market_env = check_market_env()
    bull_str = "Bull" if market_env.get("bull") is True else "Bear" if market_env.get("bull") is False else "Unknown"
    logger.info("Market: %s (S&P500 %s > 200MA %s)", bull_str, market_env.get("sp500"), market_env.get("sma200"))

    # Fetch OHLCV data
    logger.info("Fetching OHLCV for %d stocks...", len(tickers))
    raw_data = fetch_all_ohlcv(
        tickers,
        days=400,
        chunk_index=args.chunk,
        total_chunks=args.total_chunks,
    )

    # Compute RS ratings
    logger.info("Computing RS ratings...")
    returns: dict[str, float] = {}
    for ticker, df in raw_data.items():
        returns[ticker] = compute_12m_return(df)
    all_return_vals = sorted(returns.values())
    n_all = len(all_return_vals)

    def compute_rs(ticker: str) -> float:
        if ticker not in returns or n_all == 0:
            return 50.0
        my_ret = returns[ticker]
        rank = sum(1 for v in all_return_vals if v <= my_ret)
        return round(rank / n_all * 100, 1)

    # Scan all stocks
    logger.info("Scanning %d stocks...", len(raw_data))
    results = []
    for i, (ticker, raw_df) in enumerate(raw_data.items(), 1):
        if i % 100 == 0:
            logger.info("  Scanned %d/%d", i, len(raw_data))
        rs = compute_rs(ticker)
        info = stock_info.get(ticker, {})
        result = scan_stock(ticker, raw_df, rs, info)
        if result and result["score"] >= args.min_score:
            results.append(result)

    results.sort(key=lambda x: x["score"], reverse=True)

    # Fetch earnings only for top candidates (efficient)
    logger.info("Fetching earnings for top %d candidates...", min(50, len(results)))
    candidate_tickers = [r["code"] for r in results[:50]]
    earnings_map: dict[str, str] = {}
    try:
        earnings_map = fetch_upcoming_earnings(candidate_tickers, days_ahead=5)
    except Exception as e:
        logger.warning("Earnings fetch failed: %s", e)

    for r in results:
        next_earnings = earnings_map.get(r["code"])
        r["earnings_warning"]   = next_earnings is not None
        r["next_earnings_date"] = next_earnings

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    output = {
        "generated_at":  datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET"),
        "total_scanned": len(raw_data),
        "total_signals": len(results),
        "market_env":    market_env,
        "results":       results,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=None)

    logger.info(
        "Done. %d signals from %d stocks → %s",
        len(results), len(raw_data), args.output,
    )


if __name__ == "__main__":
    main()
