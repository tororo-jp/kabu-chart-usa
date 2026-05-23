"""Target price and stop-loss calculator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from patterns import Pattern

_MIN_TARGET_MARGIN = 0.02

_PATTERN_WEEKS: dict[str, tuple[int, int]] = {
    "inverse_head_shoulders": (6, 12),
    "double_bottom":          (4,  8),
    "triple_bottom":          (4,  8),
    "cup_with_handle":        (4, 10),
    "ascending_triangle":     (3,  6),
    "symmetric_triangle":     (3,  6),
    "resistance_breakout":    (2,  4),
    "bull_flag":              (1,  3),
    "channel_pullback":       (2,  4),
    "vcp":                    (2,  6),
    "perfect_order":          (4,  8),
    "ma_compression":         (2,  4),
    "ma_pullback":            (1,  3),
    "wyckoff_spring":         (4, 12),
    "new_52w_high":           (4,  8),
    "ichimoku_cloud_break":   (4,  8),
    "bb_squeeze":             (2,  4),
    "falling_wedge":          (4,  8),
    "donchian_break":         (2,  4),
    "sr_flip":                (2,  4),
    "rsi_divergence":         (2,  6),
    "macd_divergence":        (2,  6),
    "obv_divergence":         (2,  6),
    "morning_star":           (1,  3),
    "hammer":                 (1,  3),
    "bullish_engulfing":      (1,  3),
    "three_white_soldiers":   (1,  4),
}

_GC_WEEKS = {
    "5x25":   (2,  4),
    "25x75":  (4,  8),
    "75x200": (8, 16),
}

_BASIS_WEEKS = {
    "pattern": (4,  8),
    "fib_127": (6, 12),
    "fib_162": (8, 16),
    "atr3":    (2,  4),
}


def _estimate_weeks(patterns: list[Pattern], basis: str) -> tuple[int, int]:
    if basis == "pattern":
        for p in patterns:
            if p.name == "golden_cross":
                pair = p.details.get("pair", "5x25")
                return _GC_WEEKS.get(pair, (2, 8))
            if p.name in _PATTERN_WEEKS:
                return _PATTERN_WEEKS[p.name]
        return _BASIS_WEEKS["pattern"]
    return _BASIS_WEEKS.get(basis, (4, 8))


def calculate_targets(
    df: pd.DataFrame,
    patterns: list[Pattern],
    current_price: float,
) -> dict:
    atr = (
        float(df["ATR_14"].iloc[-1])
        if "ATR_14" in df.columns and not pd.isna(df["ATR_14"].iloc[-1])
        else current_price * 0.03
    )

    candidates: dict[str, float] = {}

    _PATTERN_TARGET_KEYS = {
        "inverse_head_shoulders", "double_bottom", "triple_bottom",
        "ascending_triangle", "cup_with_handle", "resistance_breakout",
        "bull_flag", "channel_pullback",
    }
    primary_pattern: Pattern | None = None
    for p in patterns:
        if p.name not in _PATTERN_TARGET_KEYS:
            continue
        t = p.details.get("target")
        if t is None:
            continue
        if float(t) > current_price * (1 + _MIN_TARGET_MARGIN):
            candidates["pattern"] = float(t)
            primary_pattern = p
            break

    swing_h = float(df["High"].rolling(60).max().iloc[-1])
    swing_l = float(df["Low"].rolling(60).min().iloc[-1])
    swing_range = swing_h - swing_l
    if swing_range > 0:
        fib_127 = swing_l + swing_range * 1.272
        fib_162 = swing_l + swing_range * 1.618
        if fib_127 > current_price * (1 + _MIN_TARGET_MARGIN):
            candidates["fib_127"] = fib_127
        if fib_162 > current_price * (1 + _MIN_TARGET_MARGIN):
            candidates["fib_162"] = fib_162

    candidates["atr3"] = current_price + atr * 3

    basis = "atr3"
    for key in ("pattern", "fib_127", "fib_162"):
        if key in candidates:
            basis = key
            break
    main_target = candidates[basis]

    stop_loss = current_price - atr * 2
    for p in patterns:
        d = p.details
        if p.name == "cup_with_handle" and "pivot" in d:
            sl = float(d["pivot"]) * 0.92
            if sl < current_price:
                stop_loss = sl
            break
        elif p.name == "vcp":
            stop_loss = current_price * 0.92
            break
    stop_loss = min(stop_loss, current_price * 0.99)

    reward = main_target - current_price
    risk   = current_price - stop_loss
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

    weeks_min, weeks_max = _estimate_weeks(patterns, basis)

    return {
        "main_target":  main_target,
        "stop_loss":    stop_loss,
        "rr_ratio":     rr_ratio,
        "target_basis": basis,
        "weeks_min":    weeks_min,
        "weeks_max":    weeks_max,
    }
