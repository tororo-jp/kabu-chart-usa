"""Wyckoff accumulation phase detector: SC, Spring, SOS."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal

from .base import Pattern


def detect_wyckoff_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 60:
        return patterns

    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values
    vol = df["Volume"].values
    n = len(close)
    vol_ma20 = np.convolve(vol, np.ones(20) / 20, mode="same")

    # ── Selling Climax (SC) Detection ─────────────────────────────────────────────
    # Large bearish candle + volume spike + long lower wick
    sc_idx = None
    for i in range(max(0, n - 60), n - 5):
        body = abs(close[i] - df["Open"].values[i])
        lower_wick = min(close[i], df["Open"].values[i]) - low[i]
        v_ratio = vol[i] / vol_ma20[i] if vol_ma20[i] > 0 else 1.0
        bearish = close[i] < df["Open"].values[i]
        if bearish and v_ratio >= 2.0 and lower_wick >= body * 0.5:
            sc_idx = i
            break

    if sc_idx is None:
        return patterns

    sc_low = low[sc_idx]

    # ── Spring Detection ──────────────────────────────────────────────────────────────
    # Price retests SC low with very low volume
    spring_idx = None
    for i in range(sc_idx + 5, n - 3):
        near_sc = abs(low[i] - sc_low) / sc_low < 0.03
        v_ratio = vol[i] / vol_ma20[i] if vol_ma20[i] > 0 else 1.0
        if near_sc and v_ratio < 0.7:
            spring_idx = i
            break

    if spring_idx is None:
        return patterns

    # ── Sign of Strength (SOS) ──────────────────────────────────────────────────────
    # Strong upward move with volume after spring
    for i in range(spring_idx + 1, n):
        price_gain = (close[i] - close[spring_idx]) / close[spring_idx]
        v_ratio = vol[i] / vol_ma20[i] if vol_ma20[i] > 0 else 1.0
        if price_gain >= 0.03 and v_ratio >= 1.5:
            # Confirm still in accumulation (within 20% of SC low)
            range_from_sc = (close[-1] - sc_low) / sc_low
            if 0 <= range_from_sc <= 0.25:
                patterns.append(Pattern(
                    name="wyckoff_spring",
                    confidence=0.65,
                    label="Wyckoff Spring (Accumulation)",
                    details={
                        "sc_low": float(sc_low),
                        "spring_low": float(low[spring_idx]),
                        "sos_price": float(close[i]),
                        "sos_vol_ratio": float(v_ratio),
                    },
                ))
            break

    return patterns
