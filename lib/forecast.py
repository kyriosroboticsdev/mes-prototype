"""
Engine 1 (model half) — near-term price forecast with a confidence band.

Uses a free, pre-built forecaster (statsmodels Holt's damped-trend exponential
smoothing). The point of the band is honesty: commodity prices are hard to
predict, so we never show a single number. The band widens with the horizon.

This is decision support, not a crystal ball — the value comes from combining
this rough forecast with the inventory reality in recommend.py.
"""

import numpy as np
import pandas as pd


def forecast_prices(weekly_prices, horizon=12, z=1.28):
    """
    Forecast `horizon` weeks ahead.

    Returns a DataFrame indexed by future weeks with columns: mean, lower, upper.
    z=1.28 gives roughly an 80% band (deliberately not 95% — we don't want to
    pretend more certainty than we have).
    """
    y = weekly_prices.dropna().astype(float)

    if len(y) < 12:
        # Not enough history to fit a trend — hold flat with a wide band.
        last = float(y.iloc[-1]) if len(y) else 0.0
        idx = _future_index(y, horizon)
        band = last * 0.05 * np.sqrt(np.arange(1, horizon + 1))
        return pd.DataFrame(
            {"mean": last, "lower": last - band, "upper": last + band}, index=idx
        )

    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        fit = ExponentialSmoothing(y, trend="add", damped_trend=True).fit()
        mean = fit.forecast(horizon)
        resid_sigma = float(np.nanstd(y - fit.fittedvalues))
    except Exception:
        # Fallback: simple linear trend over the last year of data.
        mean, resid_sigma = _linear_trend(y, horizon)

    steps = np.arange(1, horizon + 1)
    # Uncertainty grows with the square root of the horizon (random-walk-like).
    band = z * resid_sigma * np.sqrt(steps)
    return pd.DataFrame(
        {"mean": mean.values, "lower": mean.values - band, "upper": mean.values + band},
        index=mean.index,
    )


def _future_index(y, horizon):
    freq = y.index.freq or "W-FRI"
    start = y.index[-1] + pd.tseries.frequencies.to_offset(freq)
    return pd.date_range(start=start, periods=horizon, freq=freq)


def _linear_trend(y, horizon):
    window = y.iloc[-52:] if len(y) > 52 else y
    x = np.arange(len(window))
    slope, intercept = np.polyfit(x, window.values, 1)
    fitted = intercept + slope * x
    sigma = float(np.std(window.values - fitted))
    idx = _future_index(y, horizon)
    future_x = np.arange(len(window), len(window) + horizon)
    mean = pd.Series(intercept + slope * future_x, index=idx)
    return mean, sigma
