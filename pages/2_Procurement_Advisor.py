"""
Procurement Co-Pilot — buy-timing advisor (second page of the MES prototype).

Fuses three things into one recommendation:
  1. Free commodity price data + a near-term forecast (copper, aluminum).
  2. The company's own inventory & consumption reality (the real edge).
  3. A backtest proving how much the policy would have saved vs naive buying.

See DESIGN.md for the full spec. The company-side numbers are simulated and
clearly labeled; the market data is real (yfinance) with an offline fallback.
"""

import json
import os

import altair as alt
import pandas as pd
import streamlit as st

from lib.inventory_logic import material_health, buildable_units
from lib.prices import get_weekly_prices
from lib.forecast import forecast_prices
from lib.recommend import recommend
from lib.backtest import run_backtest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _load(name):
    with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


@st.cache_data(ttl=3600, show_spinner=False)
def load_prices(ticker, base_price):
    """Cached so Streamlit Cloud doesn't hit yfinance on every rerun."""
    return get_weekly_prices(ticker, base_price=base_price)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Procurement Advisor — MES Prototype",
    page_icon="📈",
    layout="wide",  # use the full screen width instead of the narrow centered column
)

materials = _load("materials.json")
profiles = _load("company_profile.json")
products = _load("products.json")

st.title("📈 Procurement Co-Pilot")
st.caption(
    "Given what you have, what you're building, and where prices are headed — "
    "should you buy now or wait, and how much?"
)
st.info(
    "**Company inventory below is simulated** (a stand-in for an ERP feed). "
    "Market prices are **real**, pulled free from Yahoo Finance.",
    icon="ℹ️",
)

# ---------------------------------------------------------------------------
# Section 1 — Can I build this product? (BOM check, works on any material)
# ---------------------------------------------------------------------------
st.header("1. Can I build it?")
st.caption("Cross-references a product's bill of materials against stock on hand.")

product = st.selectbox("Product", list(products.keys()))
bom = products[product]
on_hand = {m: profiles[m]["on_hand"] for m in profiles}

units, bottleneck = buildable_units(bom, on_hand)
c1, c2 = st.columns([1, 2])
with c1:
    st.metric("Max buildable now", f"{units} units")
with c2:
    rows = []
    for mat, per in bom.items():
        have = on_hand.get(mat, 0)
        rows.append({
            "Material": materials.get(mat, {}).get("label", mat),
            "Need / unit": per,
            "On hand": have,
            "Enough for": int(have // per) if per else "—",
            "Bottleneck": "⛔" if mat == bottleneck else "",
        })
    st.dataframe(rows, hide_index=True, use_container_width=True)
st.caption(f"Limiting material: **{bottleneck}** — that's what to watch.")

# ---------------------------------------------------------------------------
# Section 2 — Material picker + inventory health
# ---------------------------------------------------------------------------
st.header("2. Material health & buy timing")

mat_names = list(profiles.keys())
material = st.selectbox(
    "Material",
    mat_names,
    format_func=lambda m: materials.get(m, {}).get("label", m),
)
profile = profiles[material]
meta = materials.get(material, {})
health = material_health(material, profile)

m1, m2, m3, m4 = st.columns(4)
m1.metric("On hand", f"{profile['on_hand']:,} {meta.get('unit','')}")
m2.metric("Weeks of cover", f"{health['weeks_of_cover']:.1f}")
m3.metric("Reorder point", f"{health['reorder_point']:,.0f}")
m4.metric("Suggested order (EOQ)", f"{health['eoq']:,.0f}")

if health["runs_out_before_restock"]:
    st.error(
        f"⚠️ Only {health['weeks_of_cover']:.1f} weeks of cover but orders take "
        f"{profile['lead_time_weeks']} weeks — you run out before restock. Buy now.",
        icon="⏰",
    )
elif health["below_reorder"]:
    st.warning("Below the reorder point — an order is due.", icon="📦")
else:
    st.success("Stock is comfortable for now.", icon="✅")

# ---------------------------------------------------------------------------
# Section 3 — Market price + forecast + recommendation (commodities only)
# ---------------------------------------------------------------------------
ticker = meta.get("ticker")
if not ticker:
    st.info(
        f"**{meta.get('label', material)}** is an internal item with no market "
        "feed, so there's no price forecast — the inventory math above is the whole "
        "story for it. Pick copper or aluminum to see the price engine.",
        icon="🏷️",
    )
else:
    horizon = st.slider("Forecast horizon (weeks)", 4, 24, 12)
    prices, source = load_prices(ticker, profile.get("base_price", 4.0))
    fc = forecast_prices(prices, horizon=horizon)
    current_price = float(prices.iloc[-1])

    badge = "🟢 live data" if source.startswith("live") else "🟡 " + source
    st.subheader(f"Price & forecast — {meta.get('label', material)}  ·  {badge}")

    # Build a layered chart: history line + forecast line + confidence band.
    hist_df = prices.reset_index()
    hist_df.columns = ["date", "price"]
    fc_df = fc.reset_index()
    fc_df.columns = ["date", "mean", "lower", "upper"]

    hist = alt.Chart(hist_df).mark_line(color="#4c78a8").encode(
        x=alt.X("date:T", title=None), y=alt.Y("price:Q", title=f"{meta.get('unit','')} price", scale=alt.Scale(zero=False))
    )
    band = alt.Chart(fc_df).mark_area(opacity=0.2, color="#f58518").encode(
        x="date:T", y="lower:Q", y2="upper:Q"
    )
    fline = alt.Chart(fc_df).mark_line(color="#f58518", strokeDash=[5, 4]).encode(
        x="date:T", y="mean:Q"
    )
    st.altair_chart((band + hist + fline).properties(height=320), use_container_width=True)
    st.caption(
        "Solid = history. Dashed = forecast (Holt damped-trend). Shaded ≈ 80% "
        "band — commodity prices are hard to call, so we show uncertainty, not a "
        "single number."
    )

    # ---- Recommendation -------------------------------------------------
    rec = recommend(health, fc, current_price)
    st.subheader("3. Recommendation")
    color = {"BUY": "🟢", "WAI": "🟡", "HOL": "⚪", "ORD": "🟢"}.get(rec["action"][:3], "🟢")
    st.markdown(f"### {color} {rec['action']}")
    if rec["order_qty"] > 0:
        st.markdown(f"**Suggested quantity: {rec['order_qty']:,} {meta.get('unit','')}**")
    for r in rec["reasons"]:
        st.markdown(f"- {r}")

    # ---- Backtest -------------------------------------------------------
    st.subheader("4. Would this have saved money? (backtest)")
    st.caption(
        "Replays the policy week-by-week over real history (no peeking at future "
        "prices) vs a naive fixed-size policy. Leftover stock is valued at the "
        "final price so the comparison is fair."
    )
    bt = run_backtest(prices, profile)
    b1, b2, b3 = st.columns(3)
    b1.metric("Naive net cost", f"${bt['naive']['net_cost']:,.0f}")
    b2.metric("Price-aware net cost", f"${bt['smart']['net_cost']:,.0f}")
    b3.metric("Saved", f"${bt['saved']:,.0f}", f"{bt['saved_pct']:+.1f}%")
    st.line_chart(bt["cum_cost"])
    sub = (
        f"Over {bt['weeks']} weeks of history. Stockouts — "
        f"naive: {bt['naive']['stockouts']}, price-aware: {bt['smart']['stockouts']} "
        "(want both at 0: savings shouldn't come from running out)."
    )
    if bt["saved"] > 0 and bt["smart"]["stockouts"] == 0:
        st.success("✅ " + sub)
    else:
        st.info(sub)

st.divider()
st.caption("Prototype — simulated company data, real market prices. See DESIGN.md.")
