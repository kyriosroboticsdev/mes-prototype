"""
Engine 2 — inventory & consumption logic.

Pure, explainable arithmetic from standard inventory theory. No ML, no API.
This is the part a pure price-trading model never has, and it's the real value
of the tool: it knows how much you have and how fast you use it.
"""

import math


def weeks_of_cover(on_hand, weekly_use):
    """How many weeks the current stock lasts at the current usage rate."""
    if weekly_use <= 0:
        return float("inf")
    return on_hand / weekly_use


def reorder_point(weekly_use, lead_time_weeks, safety_stock):
    """Stock level at which you should place a new order.

    = demand during the lead time + a safety buffer.
    """
    return weekly_use * lead_time_weeks + safety_stock


def economic_order_quantity(weekly_use, order_cost, holding_cost_per_unit_yr):
    """Classic EOQ: the order size that balances ordering cost vs holding cost."""
    annual_demand = weekly_use * 52.0
    if holding_cost_per_unit_yr <= 0:
        return annual_demand
    return math.sqrt(2.0 * annual_demand * order_cost / holding_cost_per_unit_yr)


def material_health(name, profile):
    """Summarize one material's stock situation."""
    woc = weeks_of_cover(profile["on_hand"], profile["weekly_use"])
    rop = reorder_point(
        profile["weekly_use"], profile["lead_time_weeks"], profile["safety_stock"]
    )
    eoq = economic_order_quantity(
        profile["weekly_use"], profile["order_cost"], profile["holding_cost_per_unit_yr"]
    )
    # Slack = how many weeks of breathing room beyond the lead time. If <= 0 you
    # will run out before a freshly placed order can possibly arrive.
    slack_weeks = woc - profile["lead_time_weeks"]
    return {
        "material": name,
        "on_hand": profile["on_hand"],
        "weekly_use": profile["weekly_use"],
        "weeks_of_cover": woc,
        "reorder_point": rop,
        "eoq": eoq,
        "slack_weeks": slack_weeks,
        "below_reorder": profile["on_hand"] <= rop,
        "runs_out_before_restock": slack_weeks <= 0,
    }


def buildable_units(bom, on_hand_by_material):
    """
    Max whole units of a product you can build from current stock, plus the
    material that runs out first (the bottleneck).

    bom: {material: qty_needed_per_unit}
    on_hand_by_material: {material: qty_on_hand}
    """
    ratios = {}
    for material, qty_per_unit in bom.items():
        if qty_per_unit <= 0:
            continue
        have = on_hand_by_material.get(material, 0)
        ratios[material] = have / qty_per_unit
    if not ratios:
        return 0, None
    bottleneck = min(ratios, key=ratios.get)
    return int(math.floor(ratios[bottleneck])), bottleneck
