"""S&P 500 market environment check (price vs 200-day SMA)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def check_market_env() -> dict:
    """Return bull/bear status based on S&P 500 vs its 200-day SMA."""
    try:
        import yfinance as yf
        df = yf.download("^GSPC", period="300d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return {"bull": None, "sp500": None, "sma200": None}
        close = df["Close"].squeeze().dropna()
        if len(close) < 200:
            return {"bull": None, "sp500": None, "sma200": None}
        sma200  = float(close.rolling(200).mean().iloc[-1])
        current = float(close.iloc[-1])
        return {
            "bull":   current > sma200,
            "sp500":  round(current, 2),
            "sma200": round(sma200, 2),
        }
    except Exception as e:
        logger.warning("Market env check failed: %s", e)
        return {"bull": None, "sp500": None, "sma200": None}
