"""Scoring engine: 100-point score + win probability calculation."""

from __future__ import annotations

import pandas as pd

from indicators import (
    is_perfect_order,
    is_partial_order,
    ichimoku_three_roles,
    ma_compression_ratio,
    macd_golden_cross_days,
    count_bullish_divergences,
    obv_slope,
)
from patterns import Pattern

# ── Pattern weights ───────────────────────────────────────────────────
PATTERN_WEIGHTS: dict[str, int] = {
    "cup_with_handle":        20,
    "vcp":                    20,
    "inverse_head_shoulders": 18,
    "wyckoff_spring":         14,
    "resistance_breakout":    16,
    "ascending_triangle":     13,
    "new_52w_high":           13,
    "ma_compression":         12,
    "double_bottom":          12,
    "bull_flag":              11,
    "bb_squeeze":             10,
    "falling_wedge":          10,
    "ichimoku_cloud_break":   10,
    "perfect_order":          10,
    "sr_flip":                 9,
    "triple_bottom":           9,
    "channel_pullback":        8,
    "donchian_break":          8,
    "morning_star":            8,
    "ma_pullback":             7,
    "golden_cross":            6,
    "symmetric_triangle":      6,
    "rsi_divergence":          6,
    "rsi_hidden_divergence":   6,
    "three_white_soldiers":    6,
    "macd_divergence":         5,
    "obv_divergence":          5,
    "bullish_engulfing":       5,
    "hammer":                  4,
    "piercing_line":           3,
    "three_gap_reversal":      3,
}

# ── Pattern win rates (US market estimates) ─────────────────────────────
PATTERN_WIN_RATES: dict[str, float] = {
    "vcp":                    0.68,
    "cup_with_handle":        0.66,
    "new_52w_high":           0.64,
    "inverse_head_shoulders": 0.63,
    "ascending_triangle":     0.62,
    "wyckoff_spring":         0.61,
    "resistance_breakout":    0.61,
    "perfect_order":          0.60,
    "ichimoku_cloud_break":   0.59,
    "bull_flag":              0.59,
    "bb_squeeze":             0.58,
    "sr_flip":                0.57,
    "double_bottom":          0.57,
    "rsi_divergence":         0.56,
    "rsi_hidden_divergence":  0.56,
    "ma_pullback":            0.55,
    "channel_pullback":       0.55,
    "falling_wedge":          0.55,
    "ma_compression":         0.54,
    "triple_bottom":          0.54,
    "golden_cross":           0.53,
    "obv_divergence":         0.53,
    "macd_divergence":        0.52,
    "morning_star":           0.52,
    "donchian_break":         0.52,
    "bullish_engulfing":      0.51,
    "three_white_soldiers":   0.51,
    "symmetric_triangle":     0.50,
    "hammer":                 0.50,
    "piercing_line":          0.49,
    "three_gap_reversal":     0.48,
    "default":                0.52,
}


def calculate_score(
    df: pd.DataFrame,
    patterns: list[Pattern],
    rs: float = 50.0,
    blue_sky_info: dict | None = None,
) -> tuple[int, dict[str, int]]:
    score: dict[str, int] = {}

    # ── A. Trend Foundation (25 pts) ────────────────────────────────
    trend = 0
    if is_perfect_order(df):
        trend += 10
    elif is_partial_order(df):
        trend += 5

    if "SMA_200" in df.columns and not pd.isna(df["SMA_200"].iloc[-1]):
        if df["Close"].iloc[-1] > df["SMA_200"].iloc[-1]:
            trend += 5

    comp = ma_compression_ratio(df)
    if comp < 0.03:
        trend += 7
    elif comp < 0.05:
        trend += 4

    if ichimoku_three_roles(df):
        trend += 3

    score["trend"] = min(25, trend)

    # ── B. Pattern Recognition (35 pts) ──────────────────────────────
    qualified = sorted(
        [p for p in patterns if p.confidence >= 0.4],
        key=lambda p: PATTERN_WEIGHTS.get(p.name, 5) * p.confidence,
        reverse=True,
    )
    pattern_score = 0.0
    multiplier = 1.0
    for p in qualified:
        pattern_score += PATTERN_WEIGHTS.get(p.name, 5) * p.confidence * multiplier
        multiplier *= 0.5
    score["pattern"] = min(35, int(pattern_score))

    # ── C. Momentum (20 pts) ──────────────────────────────────────
    momentum = 0
    if "RSI_14" in df.columns and not pd.isna(df["RSI_14"].iloc[-1]):
        rsi = df["RSI_14"].iloc[-1]
        if 50 <= rsi <= 75:
            momentum += 8
        elif 75 < rsi <= 80:
            momentum += 5
        elif 40 <= rsi < 50:
            momentum += 4

    gc_days = macd_golden_cross_days(df)
    if gc_days <= 5:
        momentum += 7
    elif gc_days <= 15:
        momentum += 3

    divs = count_bullish_divergences(df)
    momentum += min(5, divs * 2)

    score["momentum"] = min(20, momentum)

    # ── D. Volume Confirmation (10 pts) ──────────────────────────────
    vol_score = 0
    if "VOL_MA_20" in df.columns and not pd.isna(df["VOL_MA_20"].iloc[-1]):
        vol_ratio = df["Volume"].iloc[-1] / df["VOL_MA_20"].iloc[-1]
        if vol_ratio >= 3.0:
            vol_score += 7
        elif vol_ratio >= 2.0:
            vol_score += 5
        elif vol_ratio >= 1.5:
            vol_score += 3

    if obv_slope(df) > 0:
        vol_score = min(10, vol_score + 3)

    score["volume"] = min(10, vol_score)

    # ── E. Liquidity (5 pts) ───────────────────────────────────────
    # Avg daily dollar volume in USD
    liq_score = 0
    if "VOL_MA_20" in df.columns and not pd.isna(df["VOL_MA_20"].iloc[-1]):
        avg_daily_value_usd = df["VOL_MA_20"].iloc[-1] * df["Close"].iloc[-1]
        adv_m = avg_daily_value_usd / 1_000_000  # million USD
        if adv_m >= 50:    # $50M+: institutional grade
            liq_score = 5
        elif adv_m >= 10:  # $10M+: standard large-cap
            liq_score = 4
        elif adv_m >= 5:   # $5M+: sufficient for swing trading
            liq_score = 3
        elif adv_m >= 1:   # $1M+: minimum acceptable
            liq_score = 1

    score["liquidity"] = liq_score

    # ── G. Relative Strength (5〘7 pts) ────────────────────────────
    if rs >= 95:
        score["rs"] = 7
    elif rs >= 80:
        score["rs"] = 5
    elif rs >= 65:
        score["rs"] = 4
    elif rs >= 50:
        score["rs"] = 2
    else:
        score["rs"] = 0

    # ── H. Blue Sky / 52-Week High Bonus (0〘3 pts) ───────────────────
    sky = blue_sky_info or {}
    if sky.get("blue_sky"):
        score["blue_sky"] = 3
    elif sky.get("at_52w_high"):
        score["blue_sky"] = 2
    else:
        score["blue_sky"] = 0

    total = sum(score.values())
    return min(100, total), score


def calculate_probability(
    total_score: int,
    patterns: list[Pattern],
    rs: float = 50.0,
) -> float:
    base_prob = 0.30 + (total_score / 100) * 0.50

    if patterns:
        total_weight = 0.0
        weighted_wr  = 0.0
        for p in patterns:
            w  = PATTERN_WEIGHTS.get(p.name, 5) * p.confidence
            wr = PATTERN_WIN_RATES.get(p.name, 0.52)
            weighted_wr  += wr * w
            total_weight += w
        pattern_prob = weighted_wr / total_weight if total_weight > 0 else 0.52
        combined = 0.60 * base_prob + 0.40 * pattern_prob
    else:
        combined = base_prob

    if rs >= 90:
        combined = min(combined * 1.05, 0.85)

    return round(min(combined, 0.85), 2)
