"""Reversal pattern detectors: IHS, double/triple bottom, cup, saucer, falling wedge."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal

from .base import Pattern


def _local_minima(series: np.ndarray, order: int = 5) -> np.ndarray:
    return signal.argrelmin(series, order=order)[0]


def _local_maxima(series: np.ndarray, order: int = 5) -> np.ndarray:
    return signal.argrelmax(series, order=order)[0]


def detect_reversal_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 60:
        return patterns

    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values
    vol = df["Volume"].values
    vol_ma20 = np.convolve(vol, np.ones(20) / 20, mode="same")

    # ── Inverse Head and Shoulders ────────────────────────────────────────────
    mins = _local_minima(low, order=5)
    if len(mins) >= 3:
        for i in range(len(mins) - 2):
            l, m, r = mins[i], mins[i + 1], mins[i + 2]
            if not (l < m < r):
                continue
            left_low = low[l]
            head_low = low[m]
            right_low = low[r]
            # Head must be the lowest
            if head_low >= left_low or head_low >= right_low:
                continue
            # Shoulders within 5%
            if abs(left_low - right_low) / left_low > 0.05:
                continue
            # Neckline = avg of the two maxima between shoulders and head
            between_lm = high[l:m]
            between_mr = high[m:r]
            if len(between_lm) == 0 or len(between_mr) == 0:
                continue
            nl1 = between_lm.max()
            nl2 = between_mr.max()
            neckline = (nl1 + nl2) / 2
            current = close[-1]
            # Breakout confirmation
            if current > neckline * 1.01:
                vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
                conf = min(1.0, 0.7 + (0.15 if vol_ratio >= 1.5 else 0))
                breakout = neckline
                target = breakout + (neckline - head_low)
                patterns.append(Pattern(
                    name="inverse_head_shoulders",
                    confidence=conf,
                    label="Inverse Head & Shoulders",
                    details={
                        "neckline": float(neckline),
                        "head_low": float(head_low),
                        "breakout": float(breakout),
                        "target": float(target),
                        "vol_ratio": float(vol_ratio),
                    },
                ))
                break

    # ── Double Bottom ──────────────────────────────────────────────────────────────
    if len(mins) >= 2:
        for i in range(len(mins) - 1):
            l, r = mins[i], mins[i + 1]
            if r - l < 20:  # at least 4 weeks apart
                continue
            b1 = low[l]
            b2 = low[r]
            if abs(b1 - b2) / b1 > 0.03:
                continue
            between = high[l:r]
            if len(between) == 0:
                continue
            neckline = between.max()
            current = close[-1]
            if current > neckline * 1.005:
                vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
                # Second bottom volume < first
                vol_pattern = vol[r] < vol[l]
                conf = 0.65 + (0.1 if vol_ratio >= 1.5 else 0) + (0.05 if vol_pattern else 0)
                conf = min(1.0, conf)
                target = neckline + (neckline - min(b1, b2))
                patterns.append(Pattern(
                    name="double_bottom",
                    confidence=conf,
                    label="Double Bottom",
                    details={
                        "neckline": float(neckline),
                        "bottom": float(min(b1, b2)),
                        "breakout": float(neckline),
                        "target": float(target),
                    },
                ))
                break

    # ── Triple Bottom ───────────────────────────────────────────────────────────────
    if len(mins) >= 3:
        for i in range(len(mins) - 2):
            l, m, r = mins[i], mins[i + 1], mins[i + 2]
            b1, b2, b3 = low[l], low[m], low[r]
            avg_b = (b1 + b2 + b3) / 3
            if all(abs(b - avg_b) / avg_b < 0.03 for b in [b1, b2, b3]):
                neckline = high[l:r].max() if r > l else high[-1]
                current = close[-1]
                if current > neckline * 1.005:
                    conf = 0.70
                    target = neckline + (neckline - avg_b)
                    patterns.append(Pattern(
                        name="triple_bottom",
                        confidence=conf,
                        label="Triple Bottom",
                        details={
                            "neckline": float(neckline),
                            "bottom": float(avg_b),
                            "target": float(target),
                        },
                    ))
                    break

    # ── Cup with Handle ───────────────────────────────────────────────────────────
    n = len(close)
    if n >= 100:
        # Look for cup: high, down, U-shape, back to high
        peak_idx = _local_maxima(high, order=10)
        if len(peak_idx) >= 1:
            peak_i = peak_idx[-1]
            if peak_i < n - 20:
                peak_price = high[peak_i]
                cup_segment = close[peak_i:]
                cup_low = cup_segment.min()
                depth = (peak_price - cup_low) / peak_price
                if 0.12 <= depth <= 0.35:
                    # Check U-shape via polynomial fit
                    x = np.arange(len(cup_segment))
                    coeffs = np.polyfit(x, cup_segment, 2)
                    if coeffs[0] > 0:  # concave up
                        right_edge = close[-10:]
                        pivot = peak_price * 0.99
                        # Handle: shallow pullback in top 1/3 of cup
                        handle_high = right_edge.max()
                        handle_low = right_edge.min()
                        handle_depth = (handle_high - handle_low) / handle_high
                        if handle_depth <= 0.15 and close[-1] > pivot * 1.005:
                            vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
                            conf = 0.65 + (0.1 if vol_ratio >= 1.5 else 0)
                            conf = min(1.0, conf)
                            cup_depth = peak_price - cup_low
                            patterns.append(Pattern(
                                name="cup_with_handle",
                                confidence=conf,
                                label="Cup with Handle",
                                details={
                                    "pivot": float(pivot),
                                    "cup_depth": float(cup_depth),
                                    "target": float(pivot + cup_depth),
                                    "breakout": float(close[-1]),
                                },
                            ))

    # ── Falling Wedge ───────────────────────────────────────────────────────────────
    if n >= 30:
        seg = 30
        seg_h = high[-seg:]
        seg_l = low[-seg:]
        x = np.arange(seg)
        slope_h = np.polyfit(x, seg_h, 1)[0]
        slope_l = np.polyfit(x, seg_l, 1)[0]
        # Both declining but lows decline slower (converging downward)
        if slope_h < 0 and slope_l < 0 and slope_l > slope_h:
            breakout = close[-1] > np.polyval(np.polyfit(x, seg_h, 1), seg - 1)
            if breakout:
                vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
                conf = 0.55 + (0.15 if vol_ratio >= 1.5 else 0)
                patterns.append(Pattern(
                    name="falling_wedge",
                    confidence=min(1.0, conf),
                    label="Falling Wedge",
                    details={"vol_ratio": float(vol_ratio)},
                ))

    return patterns
