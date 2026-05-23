"""Backtest scanner signals against actual future prices."""

from __future__ import annotations

import glob
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, date, timedelta
from itertools import groupby
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SCORE_MIN     = 60
PROB_MIN      = 0.55
RR_MIN        = 1.5
MAX_PER_DAY   = 5
COOLDOWN_DAYS = 5


def load_all_signals(data_dir: str = "docs/data") -> list[dict]:
    signals: list[dict] = []
    pattern = os.path.join(data_dir, "results_????-??-??.json")
    files = sorted(glob.glob(pattern))
    for filepath in files:
        date_str = Path(filepath).stem.replace("results_", "")
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        for r in data.get("results", []):
            signals.append({**r, "_date": d, "_date_str": date_str})
    logger.info("Loaded %d raw signals from %d files", len(signals), len(files))
    return signals


def apply_filters(signals: list[dict]) -> list[dict]:
    signals.sort(key=lambda x: (x["_date"], -x.get("score", 0)))
    selected: list[dict] = []
    last_entry: dict[str, date] = {}

    for date_str, group in groupby(signals, key=lambda x: x["_date_str"]):
        day = list(group)
        entry_date = day[0]["_date"]
        candidates = []

        for s in day:
            if s.get("score", 0) < SCORE_MIN:
                continue
            if s.get("probability", 0) < PROB_MIN:
                continue
            if s.get("rr_ratio", 0) < RR_MIN:
                continue
            code = s["code"]
            if code in last_entry:
                if (entry_date - last_entry[code]).days < COOLDOWN_DAYS:
                    continue
            candidates.append(s)

        for s in sorted(candidates, key=lambda x: -x.get("score", 0))[:MAX_PER_DAY]:
            selected.append(s)
            last_entry[s["code"]] = entry_date

    logger.info("After filter: %d signals", len(selected))
    return selected


def _fetch_history(
    tickers: list[str], start: date, end: date
) -> dict[str, pd.DataFrame]:
    cache: dict[str, pd.DataFrame] = {}
    batch_size = 30
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i: i + batch_size]
        # US tickers don't need a suffix
        try:
            raw = yf.download(
                batch,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw is None or raw.empty:
                continue
            for ticker in batch:
                try:
                    df = raw[ticker].copy() if len(batch) > 1 else raw.copy()
                    df = df[["High", "Low", "Close"]].dropna()
                    df.index = pd.to_datetime(df.index)
                    if not df.empty:
                        cache[ticker] = df
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Batch fetch error: %s", e)
        time.sleep(0.5)
    logger.info("Price history: %d/%d tickers", len(cache), len(tickers))
    return cache


def evaluate_signals(signals: list[dict]) -> list[dict]:
    if not signals:
        return []

    today = datetime.today().date()
    min_date = min(s["_date"] for s in signals) - timedelta(days=5)
    tickers = list({s["code"] for s in signals})
    price_cache = _fetch_history(tickers, min_date, today + timedelta(days=1))

    results: list[dict] = []
    for s in signals:
        ticker      = s["code"]
        entry_date  = s["_date"]
        entry_price = float(s.get("price", 0))
        target      = float(s.get("target", entry_price * 1.10))
        stop_loss   = float(s.get("stop_loss", entry_price * 0.95))
        weeks_max   = int(s.get("weeks_max", 8))
        deadline    = entry_date + timedelta(weeks=weeks_max)

        if ticker not in price_cache or entry_price <= 0:
            continue

        df = price_cache[ticker]
        future = df[df.index.date > entry_date]
        if future.empty:
            continue

        period = future[future.index.date <= deadline]

        outcome    = "open"
        exit_date  = None
        exit_price = None

        for ts, row in period.iterrows():
            if float(row["High"]) >= target:
                outcome    = "win"
                exit_date  = ts.date()
                exit_price = target
                break
            if float(row["Low"]) <= stop_loss:
                outcome    = "loss"
                exit_date  = ts.date()
                exit_price = stop_loss
                break

        if outcome == "open":
            ref = future[future.index.date <= deadline]
            last = future["Close"].iloc[-1]
            last_date = future.index[-1].date()
            if today > deadline and not ref.empty:
                exit_price = float(ref["Close"].iloc[-1])
                exit_date  = ref.index[-1].date()
                outcome    = "expired"
            else:
                exit_price = float(last)
                exit_date  = last_date

        actual_return = (
            (exit_price - entry_price) / entry_price if exit_price else None
        )
        first_pattern = (
            s["patterns"][0]["label"] if s.get("patterns") else "Unknown"
        )
        holding_days = (
            (exit_date - entry_date).days if exit_date else None
        )

        results.append({
            "date":            s["_date_str"],
            "code":            ticker,
            "name":            s.get("name", ticker),
            "score":           s.get("score"),
            "score_breakdown": s.get("score_breakdown", {}),
            "probability":     round(s.get("probability", 0), 2),
            "rr_ratio":        s.get("rr_ratio"),
            "entry_price":     entry_price,
            "target":          round(target, 2),
            "stop_loss":       round(stop_loss, 2),
            "pattern":         first_pattern,
            "weeks_max":       weeks_max,
            "outcome":         outcome,
            "exit_date":       exit_date.strftime("%Y-%m-%d") if exit_date else None,
            "exit_price":      round(exit_price, 2) if exit_price else None,
            "actual_return":   round(actual_return * 100, 2) if actual_return is not None else None,
            "holding_days":    holding_days,
        })

    return results


def build_summary(results: list[dict]) -> dict:
    completed     = [r for r in results if r["outcome"] in ("win", "loss", "expired")]
    wins          = [r for r in completed if r["outcome"] == "win"]
    losses        = [r for r in completed if r["outcome"] in ("loss", "expired")]
    losses_strict = [r for r in completed if r["outcome"] == "loss"]
    expired       = [r for r in completed if r["outcome"] == "expired"]

    if not completed:
        return {
            "total_signals": len(results),
            "completed": 0,
            "open": len(results),
        }

    rets      = [r["actual_return"] for r in completed if r["actual_return"] is not None]
    win_rets  = [r["actual_return"] for r in wins   if r["actual_return"] is not None]
    loss_rets = [r["actual_return"] for r in losses if r["actual_return"] is not None]
    avg = lambda lst: round(sum(lst) / len(lst), 2) if lst else 0.0

    gross_profit = sum(r for r in win_rets  if r > 0)
    gross_loss   = abs(sum(r for r in loss_rets if r < 0))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    sharpe_ratio = None
    if len(rets) >= 5:
        rets_dec = [r / 100 for r in rets]
        avg_ret  = sum(rets_dec) / len(rets_dec)
        var_ret  = sum((r - avg_ret) ** 2 for r in rets_dec) / (len(rets_dec) - 1)
        std_ret  = math.sqrt(var_ret)
        holding_days_list = [r["holding_days"] for r in completed if r.get("holding_days")]
        avg_days = sum(holding_days_list) / len(holding_days_list) if holding_days_list else 20
        if std_ret > 0:
            sharpe_ratio = round(avg_ret / std_ret * math.sqrt(252 / avg_days), 2)

    # Capital simulation: $10,000 starting capital, 1% risk per trade
    capital = 10_000
    peak = capital
    max_drawdown = 0.0
    capital_curve: list[dict] = [{"date": None, "capital": capital}]
    risk_amount = capital * 0.01

    for r in sorted(completed, key=lambda x: x["date"]):
        ret = r.get("actual_return")
        if ret is None:
            continue
        entry  = r.get("entry_price", 1)
        target = r.get("target", entry)
        sl     = r.get("stop_loss", entry)
        risk_per_share = entry - sl if entry > sl else entry * 0.05
        shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 0
        pnl = shares * (r["exit_price"] - entry) if r.get("exit_price") else 0
        capital += pnl
        capital = round(capital, 2)
        capital_curve.append({"date": r.get("exit_date") or r.get("date"), "capital": capital})
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak if peak > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd

    by_pat: dict[str, list] = {}
    for r in completed:
        by_pat.setdefault(r["pattern"], []).append(r)
    pattern_stats = sorted([
        {
            "pattern":    p,
            "total":      len(lst),
            "wins":       sum(1 for r in lst if r["outcome"] == "win"),
            "win_rate":   round(sum(1 for r in lst if r["outcome"] == "win") / len(lst), 3),
            "avg_return": avg([r["actual_return"] for r in lst if r["actual_return"] is not None]),
        }
        for p, lst in by_pat.items()
    ], key=lambda x: -x["total"])

    buckets = {"60-69": [], "70-79": [], "80-89": [], "90+": []}
    for r in completed:
        sc = r.get("score", 0)
        if sc >= 90:   buckets["90+"].append(r)
        elif sc >= 80: buckets["80-89"].append(r)
        elif sc >= 70: buckets["70-79"].append(r)
        else:          buckets["60-69"].append(r)
    score_stats = [
        {
            "range":      label,
            "total":      len(lst),
            "wins":       sum(1 for r in lst if r["outcome"] == "win"),
            "win_rate":   round(sum(1 for r in lst if r["outcome"] == "win") / len(lst), 3) if lst else 0,
            "avg_return": avg([r["actual_return"] for r in lst if r["actual_return"] is not None]),
        }
        for label, lst in buckets.items() if lst
    ]

    calib_bands = [
        ("<55%",   0.00, 0.55),
        ("55-60%", 0.55, 0.60),
        ("60-65%", 0.60, 0.65),
        ("65-70%", 0.65, 0.70),
        ("70%+",   0.70, 1.00),
    ]
    calibration = []
    for label, lo, hi in calib_bands:
        lst = [r for r in completed if lo <= r.get("probability", 0) < hi]
        if not lst:
            continue
        wr = sum(1 for r in lst if r["outcome"] == "win") / len(lst)
        mid_prob = (lo + hi) / 2
        calibration.append({
            "band":             label,
            "total":            len(lst),
            "actual_win_rate":  round(wr, 3),
            "predicted_center": round(mid_prob, 2),
            "calibration_err":  round(wr - mid_prob, 3),
        })

    def _avg_comp(lst, key):
        vals = [r.get("score_breakdown", {}).get(key, 0) for r in lst]
        return round(sum(vals) / len(vals), 1) if vals else None

    components = ["trend", "pattern", "momentum", "volume", "liquidity", "rs"]
    breakdown_win  = {c: _avg_comp(wins,   c) for c in components}
    breakdown_loss = {c: _avg_comp(losses, c) for c in components}

    return {
        "total_signals":   len(results),
        "completed":       len(completed),
        "open":            len(results) - len(completed),
        "wins":            len(wins),
        "losses":          len(losses_strict),
        "expired":         len(expired),
        "win_rate":        round(len(wins) / len(completed), 3),
        "avg_return_win":  avg(win_rets),
        "avg_return_loss": avg(loss_rets),
        "avg_return_all":  avg(rets),
        "profit_factor":   pf,
        "expected_value":  round(avg(win_rets) * len(wins) / len(completed)
                                  + avg(loss_rets) * len(losses) / len(completed), 2),
        "sharpe_ratio":    sharpe_ratio,
        "max_drawdown":    round(max_drawdown * 100, 1),
        "capital_start":   10_000,
        "capital_end":     capital_curve[-1]["capital"],
        "capital_return":  round((capital_curve[-1]["capital"] / 10_000 - 1) * 100, 2),
        "capital_curve":   capital_curve[1:],
        "by_pattern":      pattern_stats,
        "by_score":        score_stats,
        "calibration":     calibration,
        "breakdown_win":   breakdown_win,
        "breakdown_loss":  breakdown_loss,
    }


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="docs/data")
    p.add_argument("--output",   default="docs/data/backtest.json")
    args = p.parse_args()

    signals  = load_all_signals(args.data_dir)
    if not signals:
        logger.warning("No signal files found. Exiting.")
        return

    filtered = apply_filters(signals)
    if not filtered:
        logger.warning("No signals passed filters.")
        return

    results  = evaluate_signals(filtered)
    summary  = build_summary(results)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M ET"),
        "filter": {
            "score_min":     SCORE_MIN,
            "prob_min":      PROB_MIN,
            "rr_min":        RR_MIN,
            "max_per_day":   MAX_PER_DAY,
            "cooldown_days": COOLDOWN_DAYS,
        },
        "summary": summary,
        "signals": results,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    logger.info(
        "Done. %d signals evaluated, %d completed (win rate %.1f%%, sharpe %.2f) → %s",
        len(filtered), summary.get("completed", 0),
        summary.get("win_rate", 0) * 100,
        summary.get("sharpe_ratio") or 0,
        args.output,
    )


if __name__ == "__main__":
    main()
