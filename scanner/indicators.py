"""Technical indicators implemented with pandas/numpy only (no external TA library)."""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Core helpers ───────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - 100 / (1 + rs)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14) -> pd.Series:
    tp = (high + low + close) / 3
    mf = tp * volume
    pos = mf.where(tp > tp.shift(1), 0.0)
    neg = mf.where(tp < tp.shift(1), 0.0)
    pmf = pos.rolling(period).sum()
    nmf = neg.rolling(period).sum()
    return 100 - 100 / (1 + pmf / (nmf + 1e-10))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)

    atr = _atr(high, low, close, period)
    plus_di  = 100 * plus_dm.ewm(com=period - 1, adjust=False).mean() / (atr + 1e-10)
    minus_di = 100 * minus_dm.ewm(com=period - 1, adjust=False).mean() / (atr + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.ewm(com=period - 1, adjust=False).mean()
    return adx, plus_di, minus_di


def _psar(high: pd.Series, low: pd.Series, step: float = 0.02, max_step: float = 0.2):
    h = high.values
    l = low.values
    n = len(h)
    psar_long  = np.full(n, np.nan)
    psar_short = np.full(n, np.nan)
    if n < 2:
        return pd.Series(psar_long, index=high.index), pd.Series(psar_short, index=high.index)

    bullish = True
    af, ep, sar = step, h[0], l[0]
    for i in range(1, n):
        prev_sar = sar
        if bullish:
            sar = prev_sar + af * (ep - prev_sar)
            sar = min(sar, l[i - 1], l[max(0, i - 2)])
            if l[i] < sar:
                bullish, sar, ep, af = False, ep, l[i], step
            else:
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + step, max_step)
                psar_long[i] = sar
        else:
            sar = prev_sar + af * (ep - prev_sar)
            sar = max(sar, h[i - 1], h[max(0, i - 2)])
            if h[i] > sar:
                bullish, sar, ep, af = True, ep, h[i], step
            else:
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + step, max_step)
                psar_short[i] = sar

    return pd.Series(psar_long, index=high.index), pd.Series(psar_short, index=high.index)


def _ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
              tenkan: int = 9, kijun: int = 26, senkou: int = 52):
    tenkan_line = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_line  = (high.rolling(kijun).max()  + low.rolling(kijun).min())  / 2
    senkou_a    = ((tenkan_line + kijun_line) / 2).shift(kijun)
    senkou_b    = ((high.rolling(senkou).max() + low.rolling(senkou).min()) / 2).shift(kijun)
    chikou      = close.shift(-kijun)
    return tenkan_line, kijun_line, senkou_a, senkou_b, chikou


# ── Main compute function ───────────────────────────────────────────────

def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]

    for p in [5, 9, 12, 20, 25, 26, 50, 75, 200]:
        df[f"SMA_{p}"] = close.rolling(p).mean()
        df[f"EMA_{p}"] = _ema(close, p)

    df["MACD"]        = _ema(close, 12) - _ema(close, 26)
    df["MACD_signal"] = _ema(df["MACD"], 9)
    df["MACD_hist"]   = df["MACD"] - df["MACD_signal"]

    adx, plus_di, minus_di = _adx(high, low, close, 14)
    df["ADX"]      = adx
    df["DI_plus"]  = plus_di
    df["DI_minus"] = minus_di

    psar_l, psar_s = _psar(high, low)
    df["PSAR_long"]  = psar_l
    df["PSAR_short"] = psar_s

    t, k, sa, sb, cs = _ichimoku(high, low, close)
    df["ITS_9"]  = t
    df["IKS_26"] = k
    df["ISA_9"]  = sa
    df["ISB_26"] = sb
    df["ICS_26"] = cs

    df["RSI_14"] = _rsi(close, 14)

    low14  = low.rolling(14).min()
    high14 = high.rolling(14).max()
    k_raw  = (close - low14) / (high14 - low14 + 1e-10) * 100
    df["STOCH_K"] = k_raw.rolling(3).mean()
    df["STOCH_D"] = df["STOCH_K"].rolling(3).mean()

    df["WILLR"] = (high.rolling(14).max() - close) / (
        high.rolling(14).max() - low.rolling(14).min() + 1e-10
    ) * -100

    tp = (high + low + close) / 3
    df["CCI_20"] = (tp - tp.rolling(20).mean()) / (0.015 * tp.rolling(20).std() + 1e-10)

    df["MFI_14"] = _mfi(high, low, close, volume, 14)

    df["ROC_12"] = (close / close.shift(12) - 1) * 100

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["BB_mid"]   = bb_mid
    df["BB_upper"] = bb_mid + 2 * bb_std
    df["BB_lower"] = bb_mid - 2 * bb_std
    df["BB_width"] = (df["BB_upper"] - df["BB_lower"]) / (bb_mid + 1e-10)

    atr14 = _atr(high, low, close, 14)
    df["ATR_14"] = atr14

    kc_mid = _ema(close, 20)
    df["KC_basis"] = kc_mid
    df["KC_upper"] = kc_mid + 2 * atr14
    df["KC_lower"] = kc_mid - 2 * atr14

    df["DCH_20_upper"] = high.rolling(20).max()
    df["DCH_20_lower"] = low.rolling(20).min()
    df["DCH_55_upper"] = high.rolling(55).max()

    direction = np.where(close > close.shift(1), 1,
                np.where(close < close.shift(1), -1, 0))
    df["OBV"] = pd.Series((volume.values * direction).cumsum(), index=df.index)

    df["VOL_MA_20"] = volume.rolling(20).mean()

    mfm = ((close - low) - (high - close)) / (high - low + 1e-10)
    mfv = mfm * volume
    df["CMF_20"] = mfv.rolling(20).sum() / (volume.rolling(20).sum() + 1e-10)

    log_ret = np.log(close / close.shift(1))
    df["HV_20"] = log_ret.rolling(20).std() * np.sqrt(252)

    df["AROON_up"]   = high.rolling(26).apply(
        lambda x: float(np.argmax(x)) / 25 * 100, raw=True)
    df["AROON_down"] = low.rolling(26).apply(
        lambda x: float(np.argmin(x)) / 25 * 100, raw=True)

    return df


# ── Utility functions used by scorer / patterns ─────────────────────────────────

def obv_slope(df: pd.DataFrame, window: int = 10) -> float:
    if "OBV" not in df.columns or df["OBV"].isna().all():
        return 0.0
    obv = df["OBV"].dropna().iloc[-window:]
    if len(obv) < 3:
        return 0.0
    x = np.arange(len(obv))
    return float(np.polyfit(x, obv.values, 1)[0])


def macd_golden_cross_days(df: pd.DataFrame) -> int:
    if "MACD" not in df.columns or "MACD_signal" not in df.columns:
        return 999
    cross = (df["MACD"] > df["MACD_signal"]) & (df["MACD"].shift(1) <= df["MACD_signal"].shift(1))
    idx = cross[cross].index
    if len(idx) == 0:
        return 999
    last_gc = df.index.get_loc(idx[-1])
    return len(df) - 1 - last_gc


def count_bullish_divergences(df: pd.DataFrame) -> int:
    count = 0
    n = len(df)
    if n < 30:
        return 0
    close = df["Close"].values

    if "RSI_14" in df.columns:
        rsi = df["RSI_14"].values
        if close[-1] < close[-15] and rsi[-1] > rsi[-15]:
            count += 1

    if "MACD_hist" in df.columns:
        hist = df["MACD_hist"].values
        if close[-1] < close[-10] and hist[-1] > hist[-10]:
            count += 1

    if "OBV" in df.columns:
        obv = df["OBV"].values
        if close[-1] <= close[-10] and obv[-1] > obv[-10]:
            count += 1

    return count


def ma_compression_ratio(df: pd.DataFrame) -> float:
    mas = []
    for p in [5, 25, 75, 200]:
        col = f"SMA_{p}"
        if col in df.columns and not pd.isna(df[col].iloc[-1]):
            mas.append(df[col].iloc[-1])
    if len(mas) < 2:
        return 1.0
    price = df["Close"].iloc[-1]
    return (max(mas) - min(mas)) / price if price > 0 else 1.0


def is_perfect_order(df: pd.DataFrame) -> bool:
    mas = {}
    for p in [5, 25, 75, 200]:
        col = f"SMA_{p}"
        if col not in df.columns or len(df[col].dropna()) < 2:
            return False
        mas[p] = df[col].iloc[-1]
        if df[col].iloc[-1] <= df[col].iloc[-2]:
            return False
    price = df["Close"].iloc[-1]
    return price > mas[5] > mas[25] > mas[75] > mas[200]


def is_partial_order(df: pd.DataFrame) -> bool:
    mas = {}
    for p in [5, 25, 75]:
        col = f"SMA_{p}"
        if col not in df.columns or pd.isna(df[col].iloc[-1]):
            return False
        mas[p] = df[col].iloc[-1]
    return mas[5] > mas[25] > mas[75]


def ichimoku_three_roles(df: pd.DataFrame) -> bool:
    cols = df.columns.tolist()
    tenkan_col = next((c for c in cols if "ITS" in c), None)
    kijun_col  = next((c for c in cols if "IKS" in c), None)
    span_a_col = next((c for c in cols if "ISA" in c), None)
    span_b_col = next((c for c in cols if "ISB" in c), None)
    if not all([tenkan_col, kijun_col, span_a_col, span_b_col]):
        return False
    row = df.iloc[-1]
    try:
        tenkan = row[tenkan_col]
        kijun  = row[kijun_col]
        span_a = row[span_a_col]
        span_b = row[span_b_col]
        price  = row["Close"]
        cloud_top = max(span_a, span_b)
        return (tenkan > kijun and price > cloud_top
                and not any(pd.isna(v) for v in [tenkan, kijun, span_a, span_b]))
    except Exception:
        return False


def rs_rating(df: pd.DataFrame, all_returns: dict | None = None, code: str = "") -> float:
    if all_returns is None or code not in all_returns:
        return 50.0
    my_return = all_returns.get(code, 0.0)
    all_vals = list(all_returns.values())
    if not all_vals:
        return 50.0
    rank = sum(1 for v in all_vals if v <= my_return)
    return round(rank / len(all_vals) * 100, 1)


def compute_12m_return(df: pd.DataFrame) -> float:
    n = len(df)
    if n < 60:
        return 0.0
    c = df["Close"].values
    r_12m = (c[-1] / c[max(0, n - 252)] - 1) if n >= 252 else (c[-1] / c[0] - 1)
    r_3m  = (c[-1] / c[max(0, n - 63)]  - 1) if n >= 63  else r_12m
    return r_12m * 0.4 + r_3m * 0.6


def blue_sky_check(df: pd.DataFrame) -> dict:
    """Detect 52-week high breakout and blue-sky (multi-year high) conditions."""
    n = len(df)
    result = {"at_52w_high": False, "blue_sky": False, "sky_years": 0.0}
    if n < 63:
        return result

    close = float(df["Close"].iloc[-1])
    high  = df["High"].values

    w52 = min(n - 1, 252)
    if w52 >= 60:
        result["at_52w_high"] = close > float(high[-w52 - 1:-1].max())

    lookback = min(n - 1, 1260)
    if lookback > 252:
        hist_high = float(high[-lookback - 1:-1].max())
        if close > hist_high:
            result["blue_sky"]  = True
            result["sky_years"] = round(lookback / 252, 1)

    return result
