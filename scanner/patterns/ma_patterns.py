"""Moving average pattern detectors: golden cross, perfect order, MA compression."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Pattern


def detect_ma_patterns(df: pd.DataFrame) -> list[Pattern]:
    patterns: list[Pattern] = []
    if len(df) < 30:
        return patterns

    close = df["Close"].values

    # ── Perfect Order ───────────────────────────────────────────────────────────────
    mas = {}
    all_ok = True
    for p in [5, 25, 75, 200]:
        col = f"SMA_{p}"
        if col not in df.columns or pd.isna(df[col].iloc[-1]):
            all_ok = False
            break
        mas[p] = df[col].values

    if all_ok:
        v5, v25, v75, v200 = mas[5][-1], mas[25][-1], mas[75][-1], mas[200][-1]
        slopes_positive = all(
            mas[p][-1] > mas[p][-3] for p in [5, 25, 75, 200]
        )
        if close[-1] > v5 > v25 > v75 > v200 and slopes_positive:
            patterns.append(Pattern(
                name="perfect_order",
                confidence=0.80,
                label="Perfect Order",
                details={
                    "sma5": float(v5),
                    "sma25": float(v25),
                    "sma75": float(v75),
                    "sma200": float(v200),
                },
            ))

    # ── MA Compression ────────────────────────────────────────────────────────────
    valid_mas = []
    for p in [5, 25, 75, 200]:
        col = f"SMA_{p}"
        if col in df.columns and not pd.isna(df[col].iloc[-1]):
            valid_mas.append(df[col].iloc[-1])

    if len(valid_mas) >= 3:
        price = close[-1]
        comp_ratio = (max(valid_mas) - min(valid_mas)) / price if price > 0 else 1.0
        if comp_ratio < 0.05:
            slopes_up = all(
                (df[f"SMA_{p}"].iloc[-1] > df[f"SMA_{p}"].iloc[-5])
                for p in [5, 25, 75]
                if f"SMA_{p}" in df.columns and len(df[f"SMA_{p}"].dropna()) >= 5
            )
            conf = 0.75 if comp_ratio < 0.03 else 0.60
            conf += 0.10 if slopes_up else 0
            patterns.append(Pattern(
                name="ma_compression",
                confidence=min(1.0, conf),
                label=f"MA Compression ({comp_ratio:.1%})",
                details={
                    "compression_ratio": float(comp_ratio),
                    "slopes_up": slopes_up,
                },
            ))

    # ── Golden Cross ──────────────────────────────────────────────────────────────
    gc_pairs = [(5, 25, "Short GC", 5), (25, 75, "Mid GC", 10), (75, 200, "Long GC", 10)]
    for short, long, label, weight in gc_pairs:
        sc = f"SMA_{short}"
        lc = f"SMA_{long}"
        if sc not in df.columns or lc not in df.columns:
            continue
        sv = df[sc].dropna()
        lv = df[lc].dropna()
        if len(sv) < 2 or len(lv) < 2:
            continue
        # Cross detection: today short > long, yesterday short <= long
        cross_today = sv.iloc[-1] > lv.iloc[-1]
        cross_prev = sv.iloc[-2] <= lv.iloc[-2]
        if cross_today and cross_prev:
            conf = 0.65
            patterns.append(Pattern(
                name="golden_cross",
                confidence=conf,
                label=f"{label} ({short}MA×{long}MA)",
                details={
                    "short_ma": float(sv.iloc[-1]),
                    "long_ma": float(lv.iloc[-1]),
                    "pair": f"{short}x{long}",
                },
            ))
        # Recent GC (within last 5 days) - lower confidence
        elif cross_today:
            for j in range(2, min(6, len(sv))):
                if sv.iloc[-j] <= lv.iloc[-j]:
                    days_since = j - 1
                    conf = max(0.40, 0.60 - days_since * 0.05)
                    patterns.append(Pattern(
                        name="golden_cross",
                        confidence=conf,
                        label=f"{label} ({short}MA×{long}MA)",
                        details={
                            "short_ma": float(sv.iloc[-1]),
                            "long_ma": float(lv.iloc[-1]),
                            "days_since": days_since,
                        },
                    ))
                    break

    # ── MA Deviation Pullback ─────────────────────────────────────────────────────
    if "SMA_25" in df.columns and not pd.isna(df["SMA_25"].iloc[-1]):
        sma25 = df["SMA_25"].iloc[-1]
        dev = (close[-1] - sma25) / sma25
        if 0 <= dev <= 0.02:
            # In uptrend and near 25MA
            if all_ok and close[-1] > mas[25][-1]:
                patterns.append(Pattern(
                    name="ma_pullback",
                    confidence=0.55,
                    label="25MA Pullback",
                    details={"deviation_25ma": float(dev), "sma25": float(sma25)},
                ))

    return patterns
