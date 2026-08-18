# BNB Price + HYPE/BNB FDV on the Dashboard

Date: 2026-08-18
Status: Approved, pending implementation plan

## Goal

Add BNB price as a historical line on the interactive 6M macro trend chart in
`dashboard.html`, and add live HYPE FDV / BNB FDV as text stats, placed under
the Morning Brief's Valuation table.

## Why this is architectural, not bounded

Charting BNB historically requires a DB schema change (`daily_metrics` gains
a `bnb_price` column) and a one-off historical backfill, touching `db.py`,
`plot_macro_trend.py`, and a new backfill script in addition to
`generate_dashboard.py`. This alters a shared interface (the `daily_metrics`
schema) that multiple scripts depend on, which is why this went through the
full brainstorming design flow instead of a bounded in-chat design.

## Feasibility

Confirmed via `POST /info {"type":"meta"}` that `BNB` is a listed native perp
on Hyperliquid, so its daily closes are fetchable via the same
`candleSnapshot` endpoint already used for `HYPE` and `BTC` — no new data
source needed for price history.

## Design

### 1. Schema (`db.py`)

Add `bnb_price REAL` to `daily_metrics` via the existing
`ALTER TABLE daily_metrics ADD COLUMN` pattern (see the loop that adds
`hype_circulating_supply` etc.) so it's a no-op on databases that already
have the column. No `bnb_1d_chg`/`7d_chg`/`30d_chg` columns — only price is
charted right now; change columns can be added later if the brief text ever
needs them.

### 2. Historical backfill (`backfill_bnb.py`, new script)

One-off script, not part of the daily cron:
- Reuse the chunked `fetch_candles(symbol, start, end)` pattern from
  `backfill_since_tge.py` to pull BNB daily closes from TGE (2024-11-29) to
  today via Hyperliquid's `candleSnapshot`.
- For each returned `(date, price)`, run
  `UPDATE daily_metrics SET bnb_price = ? WHERE date = ?` directly — only
  touches the new column on existing rows, leaves every other column as-is.
  (Deliberately not reusing `upsert_daily`/`INSERT OR REPLACE`, which would
  require re-supplying every other field and risks accidentally nulling
  columns this script has no data for.)
- Run manually once after this design is implemented. Not wired into
  `run_daily_report.sh`.

### 3. Daily fetch (`plot_macro_trend.py`)

- Call `get_sdk_price_history("BNB")` (function is already generic over
  symbol, no change needed there) alongside the existing HYPE/BTC calls.
- Add `bnb_price` to the `upsert_daily()` record dict at the bottom of
  `__main__`.
- The morning brief markdown (`logs/YYYY-MM-DD.md`) and its Price Action
  table are unchanged — BNB doesn't get a brief row, per the "dashboard
  only" scope decision.

### 4. Dashboard chart (`generate_dashboard.py`)

- `load_metrics()`: add `bnb_price` to the `SELECT`.
- `build_interactive_chart()`: add a 5th trace (`go.Scatter`, BNB price) on
  a new `yaxis5`, `overlaying="y", side="right", anchor="free", position=1.07`.
  Color `#C2185B` (magenta/crimson) — chosen to stay visually distinct from the existing
  five colors already in use (`color_rev` green, `color_hype` blue,
  `color_btc` brown-amber, `color_ps` purple, plus the AQA amber elsewhere on
  the page); BNB's own brand yellow was considered and rejected as too close
  to the existing amber for the tick labels to read clearly against white.
  Widen `margin.r` (currently 170) to fit the new axis label; narrow
  `xaxis.domain` (currently `[0.0, 0.86]`) slightly to compensate.

### 5. FDV text stats (`generate_dashboard.py`)

- New `fetch_coin_market_stats(coin_id: str) -> dict`: calls
  `GET https://api.coingecko.com/api/v3/coins/{coin_id}` with
  `market_data=true` (same params/headers as the existing HYPE call in
  `plot_macro_trend.py`), returns
  `{"price": market_data.current_price.usd, "fdv": market_data.fully_diluted_valuation.usd}`.
  On any failure, returns `{"price": None, "fdv": None}` and prints to
  stderr — matching the existing `fetch_usdc_float_series()` resilience
  pattern.
- Called twice: `fetch_coin_market_stats("hyperliquid")` and
  `fetch_coin_market_stats("binancecoin")`.
- New `build_fdv_stats_html(hype_stats, bnb_stats) -> str`: renders a 4-tile
  row (HYPE Price, HYPE FDV, BNB Price, BNB FDV) reusing the existing
  `.readout-grid` / `.readout-card` CSS classes (already defined for the P/S
  explorer). Missing values render as `—`. Small flag/label ("LIVE ·
  CoinGecko") marks it as independently live-refreshed, not part of the
  frozen brief text.
- Placement: inserted directly after the `.brief-card` div's content, still
  inside "Section 02 — Morning Brief", so it sits visually right under the
  brief's own Valuation table.

### Out of scope (explicitly, per answered questions)

- No BNB line on the static matplotlib PNG (`hyperliquid_6m_macro_trend.png`)
  — dashboard.html only.
- No BNB row in the morning brief markdown/Price Action table.
- No `bnb_1d_chg`/`7d_chg`/`30d_chg` columns.

## Testing

- Run `backfill_bnb.py` once against the real DB; spot-check a handful of
  dates against Hyperliquid's own BNB candle data.
- Run `plot_macro_trend.py` for a recent date and confirm `bnb_price` lands
  in the DB row.
- Run `generate_dashboard.py` standalone and open `dashboard.html` in a
  browser: confirm the BNB line renders at a sane scale on its own axis,
  doesn't visually collide with the other 4 series/axes, and the FDV tiles
  show plausible numbers under the Morning Brief section. Also verify the
  page still renders sanely if the CoinGecko FDV fetch is made to fail
  (temporarily point at a bad URL or similar) — should show `—`, not crash.
