"""Triangle pattern detectors: ascending, symmetric, descending."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal

from .base import Pattern


def detect_triangle_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 40:
        return patterns

    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values
    vol = df["Volume"].values
    n = len(close)
    vol_ma20 = np.convolve(vol, np.ones(20) / 20, mode="same")

    seg_len = min(60, n)
    seg_h = high[-seg_len:]
    seg_l = low[-seg_len:]
    x = np.arange(seg_len)

    slope_h, intercept_h = np.polyfit(x, seg_h, 1)
    slope_l, intercept_l = np.polyfit(x, seg_l, 1)

    # Estimated convergence as % of seg
    flat_tolerance = 0.001  # per-bar

    resistance_touches = _count_touches(seg_h, intercept_h + slope_h * x, tolerance=0.01)
    support_touches = _count_touches(seg_l, intercept_l + slope_l * x, tolerance=0.01)

    vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0

    # ── Ascending Triangle ───────────────────────────────────────────────────────────
    if (
        abs(slope_h) < flat_tolerance * seg_len  # flat top
        and slope_l > 0  # rising bottom
        and resistance_touches >= 2
        and support_touches >= 2
    ):
        res_price = np.mean(seg_h[seg_h >= np.percentile(seg_h, 90)])
        current = close[-1]
        if current > res_price * 1.005 and vol_ratio >= 1.5:
            first_low = seg_l[0]
            height = res_price - first_low
            conf = 0.65 + min(0.15, (resistance_touches - 2) * 0.05)
            rsi_ok = "RSI_14" in df.columns and df["RSI_14"].values[-1] > 50
            conf += 0.05 if rsi_ok else 0
            patterns.append(Pattern(
                name="ascending_triangle",
                confidence=min(1.0, conf),
                label=f"Ascending Triangle ({resistance_touches} touches)",
                details={
                    "resistance": float(res_price),
                    "target": float(res_price + height),
                    "vol_ratio": float(vol_ratio),
                    "touch_count": int(resistance_touches),
                },
            ))

    # ── Symmetric Triangle ───────────────────────────────────────────────────────────
    elif (
        slope_h < 0  # declining top
        and slope_l > 0  # rising bottom
        and resistance_touches >= 2
        and support_touches >= 2
    ):
        # Convergence point
        if abs(slope_h - slope_l) > 1e-10:
            convergence_bar = (intercept_l - intercept_h) / (slope_h - slope_l)
            # Break at 60-75% of convergence
            pct_to_conv = (seg_len - 1) / convergence_bar if convergence_bar > 0 else 0
            good_timing = 0.60 <= pct_to_conv <= 0.80
            current = close[-1]
            upper_line = slope_h * (seg_len - 1) + intercept_h
            # Upward breakout (in uptrend context)
            if current > upper_line * 1.005 and vol_ratio >= 1.3:
                conf = 0.55 + (0.10 if good_timing else 0)
                height = abs(seg_h[0] - seg_l[0])
                patterns.append(Pattern(
                    name="symmetric_triangle",
                    confidence=min(1.0, conf),
                    label="Symmetric Triangle (Upward Break)",
                    details={
                        "target": float(current + height / 2),
                        "vol_ratio": float(vol_ratio),
                    },
                ))

    return patterns


def _count_touches(actual: np.ndarray, trendline: np.ndarray, tolerance: float = 0.01) -> int:
    """Count how many times actual touches trendline within tolerance."""
    touches = 0
    in_touch = False
    for a, t in zip(actual, trendline):
        if abs(a - t) / t <= tolerance:
            if not in_touch:
                touches += 1
                in_touch = True
        else:
            in_touch = False
    return touches
