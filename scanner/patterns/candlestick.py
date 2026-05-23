"""Candlestick pattern detectors: morning star, hammer, engulfing, three soldiers, etc."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Pattern


def detect_candlestick_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 5:
        return patterns

    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values
    v = df["Volume"].values
    n = len(c)

    def body(i):
        return abs(c[i] - o[i])

    def upper_wick(i):
        return h[i] - max(c[i], o[i])

    def lower_wick(i):
        return min(c[i], o[i]) - l[i]

    def is_bullish(i):
        return c[i] > o[i]

    def is_bearish(i):
        return c[i] < o[i]

    # ── Morning Star ─────────────────────────────────────────────────────────
    if n >= 3:
        i = n - 1
        b1_body = body(i - 2)
        b2_body = body(i - 1)
        b3_body = body(i)
        b1_bearish = is_bearish(i - 2)
        b3_bullish = is_bullish(i)
        gap_down = max(o[i - 1], c[i - 1]) < min(o[i - 2], c[i - 2])
        small_middle = b2_body < b1_body * 0.3
        strong_close = c[i] > (o[i - 2] + c[i - 2]) / 2
        vol_inc = v[i] > v[i - 2]

        if b1_bearish and b3_bullish and small_middle and strong_close and vol_inc:
            conf = 0.65 + (0.10 if gap_down else 0)
            patterns.append(Pattern(
                name="morning_star",
                confidence=min(1.0, conf),
                label="Morning Star",
                details={"gap_down": bool(gap_down)},
            ))

    # ── Hammer ───────────────────────────────────────────────────────────────────────
    if n >= 1:
        i = n - 1
        bdy = body(i)
        lw = lower_wick(i)
        uw = upper_wick(i)
        is_downtrend = c[max(0, i - 5)] > c[i]  # simplified
        if lw >= bdy * 2 and uw <= bdy * 0.3 and is_downtrend and bdy > 0:
            patterns.append(Pattern(
                name="hammer",
                confidence=0.55,
                label="Hammer",
                details={"lower_wick": float(lw), "body": float(bdy)},
            ))

    # ── Bullish Engulfing ───────────────────────────────────────────────────────────
    if n >= 2:
        i = n - 1
        if is_bearish(i - 1) and is_bullish(i):
            if c[i] > o[i - 1] and o[i] < c[i - 1]:
                patterns.append(Pattern(
                    name="bullish_engulfing",
                    confidence=0.60,
                    label="Bullish Engulfing",
                    details={"prev_close": float(c[i - 1]), "curr_open": float(o[i])},
                ))

    # ── Piercing Line ────────────────────────────────────────────────────────────────
    if n >= 2:
        i = n - 1
        if is_bearish(i - 1) and is_bullish(i):
            midpoint_prev = (o[i - 1] + c[i - 1]) / 2
            if o[i] < c[i - 1] and c[i] > midpoint_prev and c[i] < o[i - 1]:
                patterns.append(Pattern(
                    name="piercing_line",
                    confidence=0.55,
                    label="Piercing Line",
                    details={},
                ))

    # ── Three White Soldiers ────────────────────────────────────────────────────────
    if n >= 3:
        i = n - 1
        if all(is_bullish(j) for j in [i - 2, i - 1, i]):
            progressive = c[i] > c[i - 1] > c[i - 2]
            opens_inside = o[i - 1] > o[i - 2] and o[i] > o[i - 1]
            small_wicks = all(upper_wick(j) < body(j) * 0.3 for j in [i - 2, i - 1, i])
            if progressive and opens_inside and small_wicks:
                patterns.append(Pattern(
                    name="three_white_soldiers",
                    confidence=0.65,
                    label="Three White Soldiers",
                    details={"close": float(c[i])},
                ))

    # ── Three Gap Reversal ─────────────────────────────────────────────────────────
    if n >= 4:
        i = n - 1
        gaps = [
            o[i - 3] > c[i - 4] if n >= 5 else False,
            o[i - 2] > c[i - 3],
            o[i - 1] > c[i - 2],
        ]
        if all(is_bearish(j) for j in [i - 3, i - 2, i - 1]) and is_bullish(i):
            patterns.append(Pattern(
                name="three_gap_reversal",
                confidence=0.55,
                label="Three Gap Reversal",
                details={},
            ))

    return patterns
