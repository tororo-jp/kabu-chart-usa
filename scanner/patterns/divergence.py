"""Divergence detectors: RSI, MACD, OBV bullish divergence."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal

from .base import Pattern


def detect_divergence_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 30:
        return patterns

    close = df["Close"].values
    n = len(close)

    # ── RSI Bullish Divergence ──────────────────────────────────────────────────────
    if "RSI_14" in df.columns:
        rsi = df["RSI_14"].values
        valid = ~np.isnan(rsi)
        if valid.sum() >= 20:
            rsi_clean = rsi.copy()
            rsi_clean[~valid] = np.nan

            price_mins = signal.argrelmin(close, order=5)[0]
            rsi_at_price_mins = [(i, rsi_clean[i]) for i in price_mins if not np.isnan(rsi_clean[i])]

            if len(rsi_at_price_mins) >= 2:
                (i1, r1), (i2, r2) = rsi_at_price_mins[-2], rsi_at_price_mins[-1]
                # Regular bullish divergence: price lower, RSI higher
                if close[i2] < close[i1] and r2 > r1:
                    patterns.append(Pattern(
                        name="rsi_divergence",
                        confidence=0.60,
                        label="RSI Bullish Divergence",
                        details={
                            "rsi_prev": float(r1),
                            "rsi_now": float(r2),
                            "price_prev": float(close[i1]),
                            "price_now": float(close[i2]),
                        },
                    ))
                # Hidden bullish divergence: price higher, RSI lower (continuation)
                elif close[i2] > close[i1] and r2 < r1 and r2 > 40:
                    patterns.append(Pattern(
                        name="rsi_hidden_divergence",
                        confidence=0.55,
                        label="RSI Hidden Bullish Divergence (Continuation)",
                        details={
                            "rsi_prev": float(r1),
                            "rsi_now": float(r2),
                        },
                    ))

    # ── MACD Bullish Divergence ────────────────────────────────────────────────────
    if "MACD_hist" in df.columns:
        hist = df["MACD_hist"].values
        price_mins = signal.argrelmin(close, order=5)[0]
        hist_mins = signal.argrelmin(hist, order=5)[0]

        if len(price_mins) >= 2:
            i1, i2 = price_mins[-2], price_mins[-1]
            if close[i2] < close[i1]:
                # Find nearest MACD trough to each price trough
                def nearest_hist(trough_i):
                    if len(hist_mins) == 0:
                        return hist[trough_i]
                    diffs = np.abs(hist_mins - trough_i)
                    return hist[hist_mins[diffs.argmin()]]

                h1 = nearest_hist(i1)
                h2 = nearest_hist(i2)
                if h2 > h1:
                    patterns.append(Pattern(
                        name="macd_divergence",
                        confidence=0.55,
                        label="MACD Bullish Divergence",
                        details={
                            "hist_prev": float(h1),
                            "hist_now": float(h2),
                        },
                    ))

    # ── OBV Bullish Divergence ─────────────────────────────────────────────────────
    if "OBV" in df.columns:
        obv = df["OBV"].values
        recent_close = close[-20:]
        recent_obv = obv[-20:]
        price_flat_or_down = recent_close[-1] <= recent_close[0]
        obv_rising = recent_obv[-1] > recent_obv[0]

        if price_flat_or_down and obv_rising:
            patterns.append(Pattern(
                name="obv_divergence",
                confidence=0.55,
                label="OBV Bullish Divergence (Accumulation)",
                details={
                    "obv_change": float(recent_obv[-1] - recent_obv[0]),
                    "price_change_pct": float((recent_close[-1] / recent_close[0] - 1) * 100),
                },
            ))

    return patterns
