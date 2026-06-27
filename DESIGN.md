# Procurement Co-Pilot — Design Spec (v0)

A second tool for this app: a raw-materials **buy-timing advisor**. The scanner
answers *"what's on hand?"*; this answers *"so when do I buy more, and how
much?"* It fuses market-price forecasting with the company's own inventory
reality — the part a pure trading model never has.

Status: design only. Nothing here is built yet.

---

## 1. The spine

One sentence: *given what you have, what you're building, and where prices are
headed — buy now or wait, and how much?*

User-facing flow (mirrors the mental model):

1. Pick a product → check whether you have enough raw material to build it (BOM math).
2. See how many weeks of material you have left at the current consumption rate.
3. Cross-reference market price + forecast + news → get a **buy / wait**
   recommendation, with the reasoning shown.

This lives in the **same Streamlit app as a second page**, not a separate
project — it shares the inventory concept with the scanner.

## 2. Demo strategy (two tracks, on purpose)

- **Inventory / BOM logic → demo with household items.** The weeks-of-cover and
  "can I build this product?" math is material-agnostic. You can scan real
  household objects (pens, bottles, batteries) with the existing camera tool,
  treat that as live on-hand inventory, define a toy "product" whose bill of
  materials uses those items, and watch the advisor run. Tangible, works in the
  room, needs no market data.
- **Price forecasting → demo with copper + aluminum (real free data).** These
  two have the cleanest free price feeds, so they carry the forecasting and
  backtest story. Real market data is what makes the demo credible.

Keeping these decoupled means Phase 0 is demoable immediately without touching a
single price API.

## 3. Data model (the "files" you cross-reference)

Three JSON configs, same pattern as `inventory.json`. The market half is real;
the company half is **simulated and clearly labeled as such**.

`data/materials.json` — catalog + how each maps to a free price feed:

```json
{
  "copper":   {"unit": "lb",  "yf_ticker": "HG=F",  "fred_series": "PCOPPUSDM", "proxy_etf": "COPX"},
  "aluminum": {"unit": "ton", "yf_ticker": "ALI=F", "fred_series": "PALUMUSDM", "proxy_etf": "JJU"}
}
```

(Materials like lithium have no clean free spot price → proxy with an ETF such as
`LIT` and label it a proxy. Being upfront about that is a credibility gain.)

`data/company_profile.json` — the simulated company (Engine 2's input):

```json
{
  "copper": {"on_hand": 1200, "weekly_use": 150, "lead_time_weeks": 4,
             "safety_stock": 300, "order_cost": 500, "holding_cost_per_unit_yr": 1.2}
}
```

`data/products.json` — bill of materials, the "do I have enough for a product?" file:

```json
{ "cordless drill": {"copper": 0.2, "aluminum": 0.4} }
```

For the household-item demo, a parallel toy profile/product set (e.g. a "kit"
product whose BOM is pens + batteries) drives the same logic.

## 4. The three engines

### Engine 1 — Price forecasting

Use a **free, pre-built forecaster fed by free, real data** — do not hand-roll a
model or fake a dummy series.

Data (free, real):

- **yfinance** — daily prices, no API key. Futures tickers where they exist
  (`HG=F` copper, `ALI=F` aluminum); ETF proxies where they don't. Wrap fetches
  in `st.cache_data`.
- **FRED** (free, one API key) — long monthly history (`PCOPPUSDM`,
  `PALUMUSDM`) for the backtest's long horizon. Optional to start.

Model:

| Option | Why | Cost |
|---|---|---|
| **statsmodels ETS / Holt's linear trend** ✅ recommended | Free, pip, light; gives **prediction intervals natively** (the confidence band, for free); nothing to hand-tune | trivial |
| pmdarima `auto_arima` | Free, auto-selects ARIMA order — easy upgrade, also yields intervals | easy |
| Prophet | Nicer seasonality, but heavier install on Streamlit Cloud | medium |

The claim is **not** "we beat the market." It's an honest "trend + uncertainty"
that Engine 2 then exploits. The page shows history → forecast → shaded
confidence band. Single-number forecasts are banned.

### Engine 2 — Inventory & consumption (the real edge)

Pure, explainable arithmetic from standard inventory theory:

- `weeks_of_cover = on_hand / weekly_use`
- `reorder_point = weekly_use × lead_time_weeks + safety_stock`
- `slack = weeks_of_cover − lead_time_weeks` → if ≤ 0, you run out before a new
  order can arrive (**must buy now, regardless of price**)
- `EOQ = sqrt(2 × annual_demand × order_cost / holding_cost)` → baseline "normal"
  order size

This is the knowledge that lives in experts' heads and that a trading algorithm
doesn't have. It is the substance of the tool.

### Engine 3 — News context (LLM, built last)

Reuse the Gemini plumbing already in `streamlit_app.py`. A news source (NewsAPI
free tier, or GDELT — free/no key) → Gemini extracts a **structured signal**:

```json
{"material": "copper", "risk_direction": "up", "confidence": 0.7,
 "reason": "Chile mine strike; analysts expect it to persist"}
```

Structured output (not just prose) is what keeps this from being a fake AI
wrapper.

## 5. Recommendation fusion (the decision)

| Inventory slack | Forecast / risk | Recommendation |
|---|---|---|
| ≤ 0 (run out before restock) | anything | **Buy now**, qty to cover lead time + safety (more if price rising) |
| small | up / elevated risk | **Buy now**, pull-forward a larger qty (hedge) |
| large | down | **Wait**, defer the order |
| large | up + news risk | **Buy ahead** opportunistically (hedge) |

Quantity = EOQ as the base, scaled up when price is cheap/rising, down when
expensive/falling. Output is always recommendation + plain-English reasoning
citing all three engines.

## 6. Backtest (credibility centerpiece — design for it from day one)

Replay the policy over history and prove savings:

- Walk week-by-week through historical prices. **At week _t_, the forecast may
  only use data up to _t_** — no lookahead, or the result is a lie. This is the
  one thing that's fatal to get wrong.
- Simulate purchases under **your policy** vs a **naive baseline** (fixed EOQ
  order whenever the reorder point is hit, ignoring price).
- Report total spend, **$ and % saved**, and **stockout count** (proves you
  didn't "save" by running out). Chart cumulative spend for both policies.

"Saved 7% over 2 years with zero stockouts" is the most persuasive artifact in
the demo.

## 7. Repo structure & deps

```
streamlit_app.py                 # stays = scanner (home)
pages/2_Procurement_Advisor.py
lib/prices.py forecast.py inventory_logic.py context.py recommend.py backtest.py
data/materials.json company_profile.json products.json
```

New deps: `yfinance pandas statsmodels` (+ `pmdarima` optional, `fredapi` for
FRED). Cache price fetches with `st.cache_data`.

## 8. Phased roadmap

| Phase | Deliverable | "Done" looks like |
|---|---|---|
| 0 | Config files + BOM / weeks-of-cover logic | "You can build 80 drills; copper runs out in 3 wks" — demoable with household items, no ML/API |
| 1 | Real price charts (yfinance) | live price line for copper + aluminum |
| 2 | ETS forecast + confidence band | forecast + shaded band on the chart |
| 3 | Recommendation engine | "Buy 6 wks of copper now" + reasoning |
| 4 | Gemini news context | structured risk signal feeding the reco |
| 5 | Backtest + savings | "saved 7%, 0 stockouts" chart |

## 9. Honesty / evaluation notes

- Frame forecasting as **decision support, not prediction.** Always show the
  confidence band.
- The edge is inventory-aware logic + backtested savings, not a price oracle.
- Avoid the fake-AI-wrapper trap: the LLM summarizes context, it does not make
  the buy decision on its own.
