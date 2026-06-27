"""
Engine 1 (data half) — free commodity price feed.

Tries yfinance (real, free, no API key). If the network/library is unavailable
or returns too little data, falls back to a deterministic synthetic series so a
live demo NEVER crashes. The caller is told which source was used so the UI can
label sample data honestly.
"""

import hashlib

import numpy as np
import pandas as pd


def _to_weekly(series):
    """Resample to a clean weekly (Friday) series with a real frequency so the
    forecaster gets a proper date index."""
    series = series.copy()
    series.index = pd.to_datetime(series.index)
    weekly = series.resample("W-FRI").last().ffill().dropna()
    weekly.name = "price"
    return weekly


def _synthetic(ticker, base_price=4.0, weeks=156):
    """Deterministic, realistic-looking weekly price series (random walk + drift
    + mild cycle), seeded by the ticker so it's stable across reruns."""
    seed = int(hashlib.md5((ticker or "x").encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=weeks, freq="W-FRI")
    shocks = np.cumsum(rng.normal(0, base_price * 0.018, weeks))
    drift = np.linspace(0, base_price * 0.12, weeks)
    cycle = base_price * 0.05 * np.sin(np.linspace(0, 6 * np.pi, weeks))
    price = np.clip(base_price + shocks + drift + cycle, base_price * 0.4, None)
    return pd.Series(price, index=idx, name="price")


def get_weekly_prices(ticker, base_price=4.0, period="3y"):
    """
    Return (weekly_price_series, source_label).

    source_label is "live (yfinance)" or "sample data (offline)" so the UI can
    be honest about what's on screen.
    """
    if ticker:
        try:
            import yfinance as yf

            df = yf.download(
                ticker, period=period, interval="1wk",
                progress=False, auto_adjust=True,
            )
            if df is not None and len(df) > 20:
                close = df["Close"]
                # Single-ticker downloads can come back with MultiIndex columns.
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                return _to_weekly(close.dropna()), "live (yfinance)"
        except Exception:
            pass
    return _synthetic(ticker, base_price=base_price), "sample data (offline)"
