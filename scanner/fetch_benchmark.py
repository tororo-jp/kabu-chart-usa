"""
Fetch S&P 500 and NASDAQ daily close data and write to docs/data/benchmark.json.
Tries yfinance first, falls back to stooq CSV.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

PERIOD_YEARS = 2
OUTPUT = Path(__file__).parent.parent / "docs" / "data" / "benchmark.json"


def _stooq(symbol: str, d1: str, d2: str) -> list[dict]:
    url = (
        f"https://stooq.com/q/d/l/"
        f"?s={symbol}&i=d&d1={d1}&d2={d2}"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if not lines:
        return []
    # Find Close column from header row instead of assuming index 4
    header = [h.strip() for h in lines[0].split(",")]
    try:
        close_idx = header.index("Close")
        date_idx  = header.index("Date")
    except ValueError:
        return []
    rows = []
    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) <= max(close_idx, date_idx):
            continue
        date = cols[date_idx].strip()
        try:
            close = float(cols[close_idx])
        except ValueError:
            continue
        if close > 0:
            rows.append({"date": date, "close": round(close, 2)})
    rows.sort(key=lambda x: x["date"])
    return rows


def _yfinance(symbol: str, period: str = "2y") -> list[dict]:
    import yfinance as yf
    df = yf.download(symbol, period=period, auto_adjust=True, progress=False)
    if df.empty:
        return []
    # Newer yfinance returns MultiIndex columns even for single tickers
    if getattr(df.columns, "nlevels", 1) > 1:
        df.columns = df.columns.get_level_values(0)
    rows = []
    for dt, row in df.iterrows():
        try:
            close = float(row["Close"])
        except (TypeError, ValueError):
            continue
        if close > 0:
            rows.append({"date": dt.strftime("%Y-%m-%d"), "close": round(close, 2)})
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch(yf_symbol: str, stooq_symbol: str) -> list[dict]:
    today = datetime.now()
    since = today - timedelta(days=365 * PERIOD_YEARS + 30)
    d1 = since.strftime("%Y%m%d")
    d2 = today.strftime("%Y%m%d")

    try:
        data = _yfinance(yf_symbol)
        if data:
            print(f"  {yf_symbol}: {len(data)} rows via yfinance")
            return data
    except Exception as e:
        print(f"  yfinance failed for {yf_symbol}: {e}")

    try:
        data = _stooq(stooq_symbol, d1, d2)
        if data:
            print(f"  {stooq_symbol}: {len(data)} rows via stooq")
            return data
    except Exception as e:
        print(f"  stooq failed for {stooq_symbol}: {e}")

    return []


def main() -> None:
    print("Fetching benchmark data...")
    sp500  = fetch("^GSPC", "^spx")
    nasdaq = fetch("^IXIC", "^ndaq")

    if not sp500 and not nasdaq:
        print("ERROR: both benchmark fetches failed", file=sys.stderr)
        sys.exit(1)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d"),
        "sp500":  sp500,
        "nasdaq": nasdaq,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False))
    print(f"Written {OUTPUT} — S&P 500 {len(sp500)} rows, NASDAQ {len(nasdaq)} rows")


if __name__ == "__main__":
    main()
