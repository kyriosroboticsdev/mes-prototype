"""
Backtest — the credibility centerpiece.

Replays two purchasing policies week-by-week over real historical prices and
reports how much the price-aware policy would have saved vs a naive fixed-size
policy, WITHOUT running out of stock.

Honesty guardrails:
  * No lookahead. The price-aware policy only uses a trailing moving average of
    PAST prices to judge "cheap vs expensive" — never future data.
  * Fair comparison. Both policies must satisfy the same consumption. We value
    leftover ending inventory at the final price and subtract it, so a policy
    can't look cheaper just by ending with less stock (or more).
"""

import numpy as np
import pandas as pd

from lib.inventory_logic import economic_order_quantity, reorder_point


def _order_size(policy, price, trailing_avg, eoq):
    """Naive: always EOQ. Smart: buy more when price is below its recent
    average (stock up while cheap), less when above (buy the minimum)."""
    if policy == "naive" or trailing_avg is None or np.isnan(trailing_avg):
        return eoq
    if price < 0.97 * trailing_avg:
        return eoq * 2.0      # cheap relative to recent history → stock up
    if price > 1.03 * trailing_avg:
        return eoq * 0.5      # expensive → buy the minimum to get by
    return eoq


def _simulate(prices, profile, policy, ma_window=12):
    weekly_use = profile["weekly_use"]
    lead = int(profile["lead_time_weeks"])
    eoq = economic_order_quantity(
        weekly_use, profile["order_cost"], profile["holding_cost_per_unit_yr"]
    )
    rop = reorder_point(weekly_use, lead, profile["safety_stock"])
    trailing = prices.rolling(ma_window).mean()

    inv = float(profile["on_hand"])
    pending = []  # list of [arrival_week_index, qty]
    total_cost = 0.0
    units_bought = 0.0
    stockouts = 0
    cum_cost = []

    price_list = prices.tolist()
    for t, price in enumerate(price_list):
        # Receive any arrivals due this week.
        arrived = sum(q for (a, q) in pending if a == t)
        inv += arrived
        pending = [[a, q] for (a, q) in pending if a > t]

        # Consume this week's demand.
        inv -= weekly_use
        if inv < 0:
            stockouts += 1
            inv = 0.0

        # Decide whether to order (accounting for stock already in transit).
        in_transit = sum(q for (_a, q) in pending)
        if inv + in_transit <= rop:
            qty = _order_size(policy, price, trailing.iloc[t], eoq)
            total_cost += qty * price
            units_bought += qty
            pending.append([t + lead, qty])

        cum_cost.append(total_cost)

    final_price = price_list[-1]
    # Value leftover stock at the final price so neither policy is rewarded for
    # simply ending with more/less inventory.
    net_cost = total_cost - inv * final_price
    return {
        "total_cost": total_cost,
        "net_cost": net_cost,
        "units_bought": units_bought,
        "ending_inventory": inv,
        "stockouts": stockouts,
        "cum_cost": pd.Series(cum_cost, index=prices.index, name=policy),
    }


def run_backtest(weekly_prices, profile, ma_window=12):
    """Compare the price-aware policy against the naive baseline.

    Returns a dict with both results, the dollar/percent savings, and a tidy
    DataFrame of cumulative cost for charting.
    """
    prices = weekly_prices.dropna().astype(float)
    naive = _simulate(prices, profile, "naive", ma_window)
    smart = _simulate(prices, profile, "smart", ma_window)

    saved = naive["net_cost"] - smart["net_cost"]
    saved_pct = (saved / naive["net_cost"] * 100) if naive["net_cost"] else 0.0

    cum = pd.concat(
        [naive["cum_cost"].rename("Naive (fixed order)"),
         smart["cum_cost"].rename("Price-aware policy")],
        axis=1,
    )
    return {
        "naive": naive,
        "smart": smart,
        "saved": saved,
        "saved_pct": saved_pct,
        "cum_cost": cum,
        "weeks": len(prices),
    }
