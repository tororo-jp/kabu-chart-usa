"""Breakout pattern detectors: resistance break, 52w high, ichimoku, donchian, S/R flip."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal

from .base import Pattern


def detect_breakout_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 60:
        return patterns

    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values
    vol = df["Volume"].values
    n = len(close)
    vol_ma20 = np.convolve(vol, np.ones(20) / 20, mode="same")

    # ── Resistance Line Breakout ─────────────────────────────────────────────
    resistance = _find_resistance(high, window=60, tolerance=0.005)
    if resistance is not None:
        res_price, touch_count = resistance
        current = close[-1]
        if current > res_price * 1.015:
            vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
            if vol_ratio >= 1.5 and close[-1] > close[-2]:  # bullish candle
                # Nearest support
                mins = signal.argrelmin(low[-60:], order=5)[0]
                support = low[-60:][mins].max() if len(mins) > 0 else current * 0.95
                range_h = res_price - support
                conf = 0.65 + min(0.15, (touch_count - 2) * 0.05)
                conf += 0.10 if vol_ratio >= 2.0 else 0
                patterns.append(Pattern(
                    name="resistance_breakout",
                    confidence=min(1.0, conf),
                    label=f"Resistance Breakout ({touch_count} touches)",
                    details={
                        "resistance": float(res_price),
                        "touch_count": int(touch_count),
                        "breakout": float(current),
                        "target": float(res_price + range_h),
                        "nearest_support": float(support),
                        "vol_ratio": float(vol_ratio),
                    },
                ))

    # ── 52-Week High Breakout ─────────────────────────────────────────────────────
    if n >= 252:
        high_252 = high[-252:-1].max()
        if close[-1] > high_252:
            vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
            if vol_ratio >= 1.5:
                conf = 0.70 + (0.10 if vol_ratio >= 2.0 else 0)
                patterns.append(Pattern(
                    name="new_52w_high",
                    confidence=min(1.0, conf),
                    label="52-Week High Breakout",
                    details={
                        "high_252": float(high_252),
                        "current": float(close[-1]),
                        "vol_ratio": float(vol_ratio),
                    },
                ))

    # ── Ichimoku Cloud Break ──────────────────────────────────────────────
    cols = df.columns.tolist()
    span_a_col = next((c for c in cols if "ISA" in c), None)
    span_b_col = next((c for c in cols if "ISB" in c), None)
    tenkan_col = next((c for c in cols if "ITS" in c), None)
    kijun_col = next((c for c in cols if "IKS" in c), None)

    if all(c is not None for c in [span_a_col, span_b_col, tenkan_col, kijun_col]):
        row = df.iloc[-1]
        row_prev = df.iloc[-2]
        span_a = row[span_a_col]
        span_b = row[span_b_col]
        tenkan = row[tenkan_col]
        kijun = row[kijun_col]
        price = row["Close"]

        if not any(pd.isna(v) for v in [span_a, span_b, tenkan, kijun]):
            cloud_top = max(span_a, span_b)
            cloud_bot = min(span_a, span_b)

            three_roles = (tenkan > kijun and price > cloud_top)
            cloud_break = (price > cloud_top and row_prev["Close"] <= max(
                row_prev.get(span_a_col, cloud_top),
                row_prev.get(span_b_col, cloud_top),
            ))

            if three_roles:
                conf = 0.70
                patterns.append(Pattern(
                    name="ichimoku_cloud_break",
                    confidence=conf,
                    label="Ichimoku Cloud Break (3 Roles)",
                    details={
                        "cloud_top": float(cloud_top),
                        "tenkan": float(tenkan),
                        "kijun": float(kijun),
                    },
                ))
            elif cloud_break:
                patterns.append(Pattern(
                    name="ichimoku_cloud_break",
                    confidence=0.55,
                    label="Ichimoku Cloud Break",
                    details={"cloud_top": float(cloud_top)},
                ))

    # ── Donchian Breakout ────────────────────────────────────────────────────
    if "DCH_20_upper" in df.columns:
        dc20_u = df["DCH_20_upper"].values[-2]  # previous day's upper
        if close[-1] > dc20_u:
            conf = 0.55
            if "DCH_55_upper" in df.columns:
                dc55_u = df["DCH_55_upper"].values[-2]
                if close[-1] > dc55_u:
                    conf = 0.65
                    patterns.append(Pattern(
                        name="donchian_break",
                        confidence=conf,
                        label="Donchian 55-Day Break",
                        details={"dc55_upper": float(dc55_u)},
                    ))
            else:
                patterns.append(Pattern(
                    name="donchian_break",
                    confidence=conf,
                    label="Donchian 20-Day Break",
                    details={"dc20_upper": float(dc20_u)},
                ))

    # ── Support/Resistance Flip ──────────────────────────────────────────────
    if resistance is not None:
        res_price, _ = resistance
        current = close[-1]
        # Price pulled back to old resistance → now support
        near_old_res = abs(current - res_price) / res_price < 0.015
        above_res = close[-3] > res_price if n >= 3 else False
        if near_old_res and above_res:
            patterns.append(Pattern(
                name="sr_flip",
                confidence=0.60,
                label="S/R Flip (Old Resistance → New Support)",
                details={"resistance": float(res_price), "current": float(current)},
            ))

    return patterns


def _find_resistance(
    high: np.ndarray,
    window: int = 60,
    tolerance: float = 0.005,
) -> tuple[float, int] | None:
    """Find strongest horizontal resistance in last `window` bars."""
    seg = high[-window:]
    peaks = signal.argrelmax(seg, order=3)[0]
    if len(peaks) < 2:
        return None

    peak_vals = seg[peaks]

    # Cluster peaks within tolerance
    best = None
    best_count = 0
    for pv in peak_vals:
        cluster = [v for v in peak_vals if abs(v - pv) / pv <= tolerance]
        if len(cluster) > best_count:
            best_count = len(cluster)
            best = float(np.mean(cluster))

    if best is None or best_count < 2:
        return None
    return best, best_count
