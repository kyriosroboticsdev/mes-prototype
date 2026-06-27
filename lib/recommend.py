"""
Recommendation fusion — combines the inventory picture (Engine 2) with the
price forecast (Engine 1) into one buy/wait decision plus plain-English reasons.

The golden rule: if you run out before a new order can arrive, you buy now no
matter what the price is doing. Otherwise, the forecast tilts the timing and
size of the order.
"""


def recommend(health, forecast_df, current_price):
    """
    health: dict from inventory_logic.material_health
    forecast_df: DataFrame from forecast.forecast_prices (mean/lower/upper)
    current_price: latest observed price

    Returns {action, order_qty, change_pct, reasons[]}.
    """
    horizon = len(forecast_df)
    end_mean = float(forecast_df["mean"].iloc[-1])
    change_pct = (end_mean - current_price) / current_price * 100 if current_price else 0.0

    rising = change_pct > 2.0
    falling = change_pct < -2.0
    eoq = health["eoq"]
    weeks = health["weeks_of_cover"]
    lead = health["weeks_of_cover"] - health["slack_weeks"]  # recovers lead time

    reasons = [
        f"{weeks:.1f} weeks of cover at current usage; an order takes {lead:.0f} weeks to arrive.",
        f"Forecast: price {'up' if rising else 'down' if falling else 'roughly flat'} "
        f"~{change_pct:+.1f}% over the next {horizon} weeks (±band shown on chart).",
    ]

    if health["runs_out_before_restock"]:
        action = "BUY NOW"
        qty = eoq * (1.5 if rising else 1.0)
        reasons.append(
            "You run out before a replacement order could arrive — you must buy now "
            "regardless of price." + (" Price is rising, so order a larger batch." if rising else "")
        )
    elif rising and weeks < lead * 2:
        action = "BUY NOW — pull forward"
        qty = eoq * 1.5
        reasons.append(
            "Stock is getting low and price is trending up — buy a larger batch now to "
            "get ahead of the increase."
        )
    elif rising:
        action = "BUY AHEAD — hedge"
        qty = eoq
        reasons.append(
            "You don't need it yet, but the upward trend makes buying a normal batch "
            "early worthwhile as a hedge."
        )
    elif falling:
        action = "WAIT"
        qty = 0
        reasons.append(
            "Plenty of cover and the price is trending down — defer the order and "
            "buy later, cheaper."
        )
    elif health["below_reorder"]:
        action = "ORDER NORMALLY"
        qty = eoq
        reasons.append("Below the reorder point with no strong price signal — place a normal order.")
    else:
        action = "HOLD"
        qty = 0
        reasons.append("Comfortable cover and no price signal — no action needed yet.")

    return {
        "action": action,
        "order_qty": round(qty),
        "change_pct": change_pct,
        "reasons": reasons,
    }
