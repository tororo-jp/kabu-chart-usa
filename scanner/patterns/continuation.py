"""Continuation pattern detectors: bull flag, pennant, BB squeeze, VCP, channel pullback."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import signal

from .base import Pattern


def detect_continuation_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 40:
        return patterns

    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values
    vol = df["Volume"].values
    n = len(close)
    vol_ma20 = np.convolve(vol, np.ones(20) / 20, mode="same")

    # ── Bull Flag ───────────────────────────────────────────────────────────────
    pole_days = range(5, 16)
    for pd_len in pole_days:
        if n < pd_len + 10:
            continue
        pole_start = close[-(pd_len + 15)]
        pole_end = close[-15]
        pole_return = (pole_end - pole_start) / pole_start
        if 0.10 <= pole_return <= 0.30:
            flag_seg = close[-15:]
            flag_high = flag_seg.max()
            flag_low = flag_seg.min()
            flag_depth = (flag_high - flag_low) / flag_high
            x = np.arange(15)
            slope = np.polyfit(x, flag_seg, 1)[0]
            # Flag: slight downward slope, volume declining
            vol_flag = vol[-15:]
            vol_declining = vol_flag[-1] < vol_flag[0]
            if slope < 0 and flag_depth <= 0.15 and vol_declining:
                breakout = close[-1] > flag_high * 1.005
                if breakout:
                    vol_ratio = vol[-1] / vol_ma20[-1] if vol_ma20[-1] > 0 else 1.0
                    conf = 0.60 + (0.15 if vol_ratio >= 1.5 else 0)
                    pole_len = pole_end - pole_start
                    target = close[-1] + pole_len
                    patterns.append(Pattern(
                        name="bull_flag",
                        confidence=min(1.0, conf),
                        label="Bull Flag",
                        details={
                            "pole_return": float(pole_return),
                            "target": float(target),
                            "vol_ratio": float(vol_ratio),
                        },
                    ))
                    break

    # ── BB Squeeze ─────────────────────────────────────────────────────────────────
    if "BB_width" in df.columns and "KC_upper" in df.columns and "KC_lower" in df.columns:
        bb_width = df["BB_width"].values
        bb_u = df["BB_upper"].values
        bb_l = df["BB_lower"].values
        kc_u = df["KC_upper"].values
        kc_l = df["KC_lower"].values
        # John Carter squeeze: BB inside KC
        squeeze = (bb_u[-1] < kc_u[-1]) and (bb_l[-1] > kc_l[-1])
        if squeeze:
            # Historical low of BB width
            valid = bb_width[~np.isnan(bb_width)]
            if len(valid) >= 20:
                min_125 = np.nanmin(valid[-125:]) if len(valid) >= 125 else np.nanmin(valid)
                is_low = bb_width[-1] <= min_125 * 1.1
                upward_bias = (
                    ("SMA_20" in df.columns and close[-1] > df["SMA_20"].values[-1])
                    and ("RSI_14" in df.columns and df["RSI_14"].values[-1] > 50)
                )
                conf = 0.55 + (0.1 if is_low else 0) + (0.1 if upward_bias else 0)
                patterns.append(Pattern(
                    name="bb_squeeze",
                    confidence=min(1.0, conf),
                    label="BB Squeeze",
                    details={"bb_width": float(bb_width[-1]), "squeeze_john_carter": True},
                ))

    # ── VCP (Volatility Contraction Pattern) ─────────────────────────────────────
    vcp = _detect_vcp(close, high, low, vol, vol_ma20)
    if vcp:
        patterns.append(vcp)

    # ── Channel Pullback ───────────────────────────────────────────────────────────
    if n >= 40:
        seg = 40
        seg_h = high[-seg:]
        seg_l = low[-seg:]
        x = np.arange(seg)
        slope_h = np.polyfit(x, seg_h, 1)[0]
        slope_l = np.polyfit(x, seg_l, 1)[0]
        # Parallel upward channel
        if slope_h > 0 and slope_l > 0 and abs(slope_h - slope_l) / max(abs(slope_h), abs(slope_l)) < 0.5:
            channel_low = np.polyval(np.polyfit(x, seg_l, 1), seg - 1)
            channel_high = np.polyval(np.polyfit(x, seg_h, 1), seg - 1)
            near_lower = close[-1] <= channel_low * 1.02
            if near_lower:
                conf = 0.55
                if "RSI_14" in df.columns and df["RSI_14"].values[-1] < 50:
                    conf += 0.05
                patterns.append(Pattern(
                    name="channel_pullback",
                    confidence=min(1.0, conf),
                    label="Channel Pullback",
                    details={
                        "channel_low": float(channel_low),
                        "channel_high": float(channel_high),
                        "target": float(channel_high),
                    },
                ))

    return patterns


def _detect_vcp(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    vol_ma20: np.ndarray,
) -> Pattern | None:
    n = len(close)
    if n < 60:
        return None

    # Find significant peaks → troughs to measure contractions
    from scipy.signal import argrelmax, argrelmin
    peaks = argrelmax(high, order=5)[0]
    troughs = argrelmin(low, order=5)[0]

    if len(peaks) < 2 or len(troughs) < 2:
        return None

    # Look for 3 contracting corrections in last 60 days
    recent_peaks = [i for i in peaks if i >= n - 60]
    recent_troughs = [i for i in troughs if i >= n - 60]

    if len(recent_peaks) < 2 or len(recent_troughs) < 3:
        return None

    contractions = []
    for i in range(min(len(recent_peaks), len(recent_troughs)) - 1):
        p = recent_peaks[i]
        t = recent_troughs[i]
        if t > p:
            depth = (high[p] - low[t]) / high[p]
            v_ratio = vol[t] / vol_ma20[t] if vol_ma20[t] > 0 else 1.0
            contractions.append((depth, v_ratio))

    if len(contractions) < 2:
        return None

    # Check contracting depth and volume
    depths = [c[0] for c in contractions]
    vols = [c[1] for c in contractions]
    depth_contracting = all(depths[i] > depths[i + 1] for i in range(len(depths) - 1))
    vol_contracting = all(vols[i] > vols[i + 1] for i in range(len(vols) - 1))

    if depth_contracting and vol_contracting and depths[-1] < 0.12:
        # Final contraction should be very tight
        final_tight = depths[-1] < 0.08
        conf = 0.65 + (0.10 if final_tight else 0)
        return Pattern(
            name="vcp",
            confidence=min(1.0, conf),
            label="VCP (Volatility Contraction)",
            details={
                "contractions": len(contractions),
                "final_depth": float(depths[-1]),
            },
        )
    return None
