# BNB Price Chart + HYPE/BNB FDV Stats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add BNB price as a 5th historical line on the interactive dashboard macro chart, and add live HYPE/BNB fully-diluted-valuation (FDV) text stats under the Morning Brief section.

**Architecture:** Clone the existing BTC price-tracking pattern for BNB end-to-end (schema column → one-off historical backfill → daily fetch/persist → chart trace), since BNB is a listed native perp on Hyperliquid with the same `candleSnapshot` history BTC/HYPE already use. FDV stats are a separate, independent live-only addition (not persisted to the DB) using CoinGecko's `/coins/{id}` endpoint, which returns `fully_diluted_valuation.usd` directly.

**Tech Stack:** Python, sqlite3, pandas, plotly (dashboard chart), requests (CoinGecko/Hyperliquid HTTP), Jinja-less f-string HTML templating (matches existing `generate_dashboard.py` style).

**Spec:** `docs/superpowers/specs/2026-08-18-bnb-price-fdv-design.md`

**Testing approach:** This repo has no pytest suite or `tests/` directory (confirmed: `requirements.txt` has no test framework, and the only `test_*.py` files on disk belong to an unrelated project in `.worktrees/`). The existing convention, documented in `CLAUDE.md`'s "Common Tasks" section, is manual verification via `sqlite3` queries and running the actual scripts against live data/DB. Each task below follows that convention: an inline `python3 -c "..."` check for schema/function-level verification, plus running the real script for end-to-end verification. This is a deliberate deviation from the writing-plans skill's default TDD-with-a-test-file pattern, matching "follow established patterns" for existing codebases — introducing a new test framework for a 5-file data-pipeline repo would be scope creep (YAGNI).

## Global Constraints

- New DB column name: `bnb_price` (REAL). No `bnb_1d_chg`/`7d_chg`/`30d_chg` columns.
- TGE date for backfill: `2024-11-29` (matches `backfill_since_tge.py`'s `TGE_DATE`).
- BNB chart trace color: `#0E7C86` (teal) — chosen to stay visually distinct from the 5 colors already on the page (green/blue/brown-amber/purple/amber). BNB's brand yellow was considered and rejected as too close to the existing amber.
- BNB chart axis: `yaxis5`, `overlaying="y", side="right", anchor="free", position=1.07`.
- CoinGecko coin ids: `"hyperliquid"` (HYPE) and `"binancecoin"` (BNB).
- No BNB line on the static matplotlib PNG (`hyperliquid_6m_macro_trend.png`) — dashboard.html only.
- No BNB row in the morning brief markdown (`logs/YYYY-MM-DD.md`) or its Price Action table.
- FDV stats placement: directly under the `.brief-card` div, still inside "Section 02 — Morning Brief".

---

### Task 1: Add `bnb_price` column to the DB schema

**Files:**
- Modify: `db.py:29-31` (CREATE TABLE), `db.py:35-41` (ALTER loop), `db.py:61-89` (`upsert_daily`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `daily_metrics.bnb_price` column (REAL, nullable). `upsert_daily(db_path, record)` now persists `record.get('bnb_price')` if present.

- [ ] **Step 1: Add `bnb_price` to the `CREATE TABLE` statement**

In `db.py`, change:

```python
            hype_market_cap REAL,
            hype_ps_ratio REAL,
            created_at       TEXT
```

to:

```python
            hype_market_cap REAL,
            hype_ps_ratio REAL,
            bnb_price REAL,
            created_at       TEXT
```

- [ ] **Step 2: Add `bnb_price` to the `ALTER TABLE` migration loop**

In `db.py`, change:

```python
    for column_name in (
        "hype_circulating_supply",
        "hype_total_supply",
        "hype_circulating_pct",
        "hype_market_cap",
        "hype_ps_ratio",
    ):
```

to:

```python
    for column_name in (
        "hype_circulating_supply",
        "hype_total_supply",
        "hype_circulating_pct",
        "hype_market_cap",
        "hype_ps_ratio",
        "bnb_price",
    ):
```

- [ ] **Step 3: Add `bnb_price` to `upsert_daily`'s INSERT statement**

In `db.py`, change the `cursor.execute(...)` call inside `upsert_daily` from:

```python
    cursor.execute("""
        INSERT OR REPLACE INTO daily_metrics (
            date, hype_price, hype_1d_chg, hype_7d_chg, hype_30d_chg,
            btc_price, btc_1d_chg, btc_7d_chg, btc_30d_chg,
            revenue_daily, revenue_7d_avg, revenue_30d_avg, revenue_7d_vs_30d,
            hype_circulating_supply, hype_total_supply, hype_circulating_pct,
            hype_market_cap, hype_ps_ratio, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record['date'],
        record.get('hype_price'),
        record.get('hype_1d_chg'),
        record.get('hype_7d_chg'),
        record.get('hype_30d_chg'),
        record.get('btc_price'),
        record.get('btc_1d_chg'),
        record.get('btc_7d_chg'),
        record.get('btc_30d_chg'),
        record.get('revenue_daily'),
        record.get('revenue_7d_avg'),
        record.get('revenue_30d_avg'),
        record.get('revenue_7d_vs_30d'),
        record.get('hype_circulating_supply'),
        record.get('hype_total_supply'),
        record.get('hype_circulating_pct'),
        record.get('hype_market_cap'),
        record.get('hype_ps_ratio'),
        record['created_at']
    ))
```

to:

```python
    cursor.execute("""
        INSERT OR REPLACE INTO daily_metrics (
            date, hype_price, hype_1d_chg, hype_7d_chg, hype_30d_chg,
            btc_price, btc_1d_chg, btc_7d_chg, btc_30d_chg,
            revenue_daily, revenue_7d_avg, revenue_30d_avg, revenue_7d_vs_30d,
            hype_circulating_supply, hype_total_supply, hype_circulating_pct,
            hype_market_cap, hype_ps_ratio, bnb_price, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record['date'],
        record.get('hype_price'),
        record.get('hype_1d_chg'),
        record.get('hype_7d_chg'),
        record.get('hype_30d_chg'),
        record.get('btc_price'),
        record.get('btc_1d_chg'),
        record.get('btc_7d_chg'),
        record.get('btc_30d_chg'),
        record.get('revenue_daily'),
        record.get('revenue_7d_avg'),
        record.get('revenue_30d_avg'),
        record.get('revenue_7d_vs_30d'),
        record.get('hype_circulating_supply'),
        record.get('hype_total_supply'),
        record.get('hype_circulating_pct'),
        record.get('hype_market_cap'),
        record.get('hype_ps_ratio'),
        record.get('bnb_price'),
        record['created_at']
    ))
```

- [ ] **Step 4: Verify the schema change**

Run:

```bash
cd /Users/elaineye/agent/hyperliquid_stats
python3 -c "
import sqlite3, tempfile, os
from pathlib import Path
from db import init_db, upsert_daily

fd, path = tempfile.mkstemp(suffix='.db')
os.close(fd)
db_path = Path(path)
init_db(db_path)
upsert_daily(db_path, {'date': '2026-01-01', 'bnb_price': 612.34, 'created_at': '2026-01-01T00:00:00'})
conn = sqlite3.connect(db_path)
row = conn.execute('SELECT date, bnb_price FROM daily_metrics WHERE date=?', ('2026-01-01',)).fetchone()
conn.close()
os.unlink(db_path)
assert row == ('2026-01-01', 612.34), row
print('OK', row)
"
```

Expected output: `OK ('2026-01-01', 612.34)`

- [ ] **Step 5: Run `init_db` against the real local DB so the column exists there too**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
python3 -c "from pathlib import Path; from db import init_db; init_db(Path('hyperliquid_stats.db'))"
sqlite3 hyperliquid_stats.db "PRAGMA table_info(daily_metrics)" | grep bnb_price
```

Expected: a line containing `bnb_price` and `REAL`.

- [ ] **Step 6: Commit**

```bash
git add db.py
git commit -m "Add bnb_price column to daily_metrics schema"
```

---

### Task 2: Backfill historical `bnb_price` on existing rows

**Files:**
- Create: `backfill_bnb.py`

**Interfaces:**
- Consumes: `backfill_since_tge.fetch_candles(symbol: str, start: datetime, end: datetime) -> pd.DataFrame` (index = UTC `pd.Timestamp` dates, one column `f"{symbol}_price"`); `backfill_since_tge.TGE_DATE` (`datetime(2024, 11, 29, tzinfo=timezone.utc)`); `backfill_since_tge.DB_PATH`. Depends on Task 1 (the `bnb_price` column must already exist on the real DB).
- Produces: `update_bnb_prices(db_path: Path, bnb_df: pd.DataFrame) -> int` (rows updated), used by this script's own `main()`. Not consumed by later tasks.

- [ ] **Step 1: Write `backfill_bnb.py`**

```python
#!/usr/bin/env python3
"""One-off backfill: populate bnb_price on existing daily_metrics rows.

Fetches BNB daily closes from Hyperliquid's candleSnapshot since TGE and
UPDATEs only the bnb_price column on matching existing rows -- does not
touch any other column and does not insert new rows. Not part of the daily
cron; run manually once. See
docs/superpowers/specs/2026-08-18-bnb-price-fdv-design.md.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from backfill_since_tge import DB_PATH, TGE_DATE, fetch_candles


def update_bnb_prices(db_path: Path, bnb_df: pd.DataFrame) -> int:
    """UPDATE bnb_price for existing rows matching each date in bnb_df.

    Only touches rows that already exist (UPDATE, not INSERT), and only the
    bnb_price column on those rows. Returns the number of rows updated.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    updated = 0
    for ts, row in bnb_df.iterrows():
        date_str = ts.strftime("%Y-%m-%d")
        cursor.execute(
            "UPDATE daily_metrics SET bnb_price = ? WHERE date = ?",
            (float(row["BNB_price"]), date_str),
        )
        updated += cursor.rowcount
    conn.commit()
    conn.close()
    return updated


def main() -> int:
    end = datetime.now(timezone.utc)
    print(f"Backfilling BNB price {TGE_DATE.date()} -> {end.date()}")
    bnb_df = fetch_candles("BNB", TGE_DATE, end)
    if bnb_df.empty:
        print("No BNB candle data returned; aborting.")
        return 1
    updated = update_bnb_prices(DB_PATH, bnb_df)
    print(f"Updated bnb_price on {updated} existing row(s) in {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Back up the real DB before running a one-off mutating script**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
cp hyperliquid_stats.db "hyperliquid_stats.db.bak-$(date +%Y%m%d)"
```

- [ ] **Step 3: Run the backfill against the real local DB**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
python backfill_bnb.py
```

Expected: prints `Backfilling BNB price 2024-11-29 -> <today>`, then a per-chunk `BNB: N rows ...` line (from the reused `fetch_candles`), then `Updated bnb_price on N existing row(s) in .../hyperliquid_stats.db` where N is close to the total row count in `daily_metrics`.

- [ ] **Step 4: Spot-check the backfilled data**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
sqlite3 hyperliquid_stats.db "SELECT COUNT(*) AS total, COUNT(bnb_price) AS with_bnb FROM daily_metrics"
sqlite3 hyperliquid_stats.db "SELECT date, bnb_price FROM daily_metrics ORDER BY date DESC LIMIT 5"
```

Expected: `with_bnb` close to `total` (a handful of the earliest TGE-era rows may be missing if BNB candles don't go back that far), and the 5 most recent `bnb_price` values look like plausible real BNB prices (roughly $500-$1500 range as of 2026), not `0` or `NULL`.

- [ ] **Step 5: Commit**

```bash
git add backfill_bnb.py
git commit -m "Add one-off BNB price backfill script, run against local DB"
```

---

### Task 3: Fetch and persist `bnb_price` in the daily pipeline

**Files:**
- Modify: `plot_macro_trend.py:541-546` (fetch calls + guard), `plot_macro_trend.py` (after the BTC print block, ~line 576), `plot_macro_trend.py` (inside the `upsert_daily(...)` record dict, ~lines 600-619)

**Interfaces:**
- Consumes: `get_sdk_price_history(symbol: str) -> pd.DataFrame | None` (already defined in this file, generic over symbol — no change needed to the function itself); `db.upsert_daily` now accepting `record['bnb_price']` (from Task 1).
- Produces: `daily_metrics.bnb_price` populated going forward on every daily cron run. Not consumed by earlier tasks; Task 4 depends on this data existing in the DB.

- [ ] **Step 1: Fetch BNB price history alongside HYPE/BTC**

In `plot_macro_trend.py`, change:

```python
if __name__ == "__main__":
    hype_df = get_sdk_price_history("HYPE")
    btc_df = get_sdk_price_history("BTC")
    rev_df = get_protocol_revenue_history()

    if all(d is not None for d in [hype_df, btc_df, rev_df]):
```

to:

```python
if __name__ == "__main__":
    hype_df = get_sdk_price_history("HYPE")
    btc_df = get_sdk_price_history("BTC")
    bnb_df = get_sdk_price_history("BNB")
    rev_df = get_protocol_revenue_history()

    if all(d is not None for d in [hype_df, btc_df, bnb_df, rev_df]):
```

- [ ] **Step 2: Compute and print the current BNB price**

In `plot_macro_trend.py`, right after this existing block:

```python
        btc_now  = btc_df['BTC_price'].iloc[-1]
        btc_prev = btc_df['BTC_price'].iloc[-2]
        btc_7d   = btc_df['BTC_price'].iloc[-8] if len(btc_df) >= 8 else btc_df['BTC_price'].iloc[0]
        btc_30d  = btc_df['BTC_price'].iloc[-31] if len(btc_df) >= 31 else btc_df['BTC_price'].iloc[0]
        btc_1d_chg = (btc_now/btc_prev-1)*100
        btc_7d_chg = (btc_now/btc_7d-1)*100
        btc_30d_chg = (btc_now/btc_30d-1)*100
        print(f"BTC Price:     ${btc_now:,.0f}  ({btc_1d_chg:+.1f}% 1d | {btc_7d_chg:+.1f}% 7d | {btc_30d_chg:+.1f}% 30d)")
```

add:

```python
        bnb_now = bnb_df['BNB_price'].iloc[-1]
        print(f"BNB Price:     ${bnb_now:,.2f}")
```

(This print line is informational only for the operator — `run_daily_report.sh` greps stdout for specific known labels like `"HYPE Price:"` and `"BTC Price:"`; a `"BNB Price:"` line is not matched by any of its regexes, so it's safely ignored by the markdown-generation step and cannot break it.)

- [ ] **Step 3: Persist `bnb_price` in the DB record**

In `plot_macro_trend.py`, inside the `upsert_daily(DB_PATH, {...})` call, change:

```python
            'btc_price': float(btc_now),
            'btc_1d_chg': float(btc_1d_chg),
            'btc_7d_chg': float(btc_7d_chg),
            'btc_30d_chg': float(btc_30d_chg),
            'revenue_daily': float(latest_rev),
```

to:

```python
            'btc_price': float(btc_now),
            'btc_1d_chg': float(btc_1d_chg),
            'btc_7d_chg': float(btc_7d_chg),
            'btc_30d_chg': float(btc_30d_chg),
            'bnb_price': float(bnb_now),
            'revenue_daily': float(latest_rev),
```

- [ ] **Step 4: Verify against a real recent date**

Pick a date already present in the DB (so this is a safe, idempotent re-run) and run the script directly:

```bash
cd /Users/elaineye/agent/hyperliquid_stats
source .venv/bin/activate
python plot_macro_trend.py 2026-08-17
```

Expected: stdout includes a `BNB Price:     $<number>` line, the script completes without a traceback, and prints `Metrics persisted to database: ...`.

- [ ] **Step 5: Confirm the persisted value**

```bash
sqlite3 hyperliquid_stats.db "SELECT date, btc_price, bnb_price FROM daily_metrics WHERE date='2026-08-17'"
```

Expected: a row with a non-null `bnb_price` in a plausible range.

- [ ] **Step 6: Commit**

```bash
git add plot_macro_trend.py
git commit -m "Fetch and persist BNB price in the daily pipeline"
```

---

### Task 4: Add the BNB trace to the interactive dashboard chart

**Files:**
- Modify: `generate_dashboard.py:104-110` (`load_metrics` SELECT), `generate_dashboard.py:131-137` (color vars), `generate_dashboard.py:164-171` (add trace after BTC trace), `generate_dashboard.py:182-269` (`fig.update_layout`: margin, xaxis domain, new `yaxis5`)

**Interfaces:**
- Consumes: `daily_metrics.bnb_price` (populated by Tasks 1-3).
- Produces: `build_interactive_chart(df)` renders a 5th BNB trace when `df["bnb_price"]` has any non-null values. No change to the function's signature or return type (still returns an HTML fragment `str`).

- [ ] **Step 1: Select `bnb_price` in `load_metrics`**

In `generate_dashboard.py`, change:

```python
        df = pd.read_sql_query(
            "SELECT date, hype_price, btc_price, revenue_daily, "
            "revenue_7d_avg, hype_ps_ratio, hype_market_cap "
            "FROM daily_metrics ORDER BY date ASC",
            conn,
            parse_dates=["date"],
        )
```

to:

```python
        df = pd.read_sql_query(
            "SELECT date, hype_price, btc_price, bnb_price, revenue_daily, "
            "revenue_7d_avg, hype_ps_ratio, hype_market_cap "
            "FROM daily_metrics ORDER BY date ASC",
            conn,
            parse_dates=["date"],
        )
```

- [ ] **Step 2: Add the BNB color constant**

In `generate_dashboard.py`, change:

```python
    color_rev = "#0B6E4F"
    color_hype = "#1A4FA8"
    color_btc = "#8A5C00"
    color_ps = "#7A3DAA"
    grid = "rgba(24,24,15,0.08)"
```

to:

```python
    color_rev = "#0B6E4F"
    color_hype = "#1A4FA8"
    color_btc = "#8A5C00"
    color_ps = "#7A3DAA"
    color_bnb = "#0E7C86"
    grid = "rgba(24,24,15,0.08)"
```

- [ ] **Step 3: Add the BNB trace after the BTC trace**

In `generate_dashboard.py`, right after this existing block:

```python
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["btc_price"],
        name="BTC Price",
        mode="lines",
        line=dict(color=color_btc, width=1.6, dash="dot"),
        yaxis="y3",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>BTC: $%{y:,.0f}<extra></extra>",
    ))
```

add:

```python
    if df["bnb_price"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["bnb_price"],
            name="BNB Price",
            mode="lines",
            line=dict(color=color_bnb, width=1.6, dash="dash"),
            yaxis="y5",
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>BNB: $%{y:,.0f}<extra></extra>",
        ))
```

- [ ] **Step 4: Widen the right margin and narrow the x-axis domain to fit the 5th axis**

In `generate_dashboard.py`, change:

```python
        margin=dict(l=80, r=170, t=70, b=70),
```

to:

```python
        margin=dict(l=80, r=220, t=70, b=70),
```

And change:

```python
        xaxis=dict(
            domain=[0.0, 0.86],
```

to:

```python
        xaxis=dict(
            domain=[0.0, 0.82],
```

- [ ] **Step 5: Add the `yaxis5` layout entry**

In `generate_dashboard.py`, right after this existing block (the end of `yaxis4`):

```python
        yaxis4=dict(
            title=dict(text="HYPE P/S",
                       font=dict(color=color_ps, size=12)),
            ticksuffix="x", tickformat=".0f",
            overlaying="y", side="right", anchor="free", position=1.0,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_ps),
            showgrid=False, zeroline=False,
        ),
    )
```

add a `yaxis5` entry before the closing `)`:

```python
        yaxis4=dict(
            title=dict(text="HYPE P/S",
                       font=dict(color=color_ps, size=12)),
            ticksuffix="x", tickformat=".0f",
            overlaying="y", side="right", anchor="free", position=1.0,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_ps),
            showgrid=False, zeroline=False,
        ),
        yaxis5=dict(
            title=dict(text="BNB Price",
                       font=dict(color=color_bnb, size=12)),
            tickprefix="$", tickformat=".2s",
            overlaying="y", side="right", anchor="free", position=1.07,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_bnb),
            showgrid=False, zeroline=False,
        ),
    )
```

- [ ] **Step 6: Verify the chart builds without error**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
source .venv/bin/activate
python3 -c "
from generate_dashboard import load_metrics, build_interactive_chart
df = load_metrics()
html = build_interactive_chart(df)
assert 'BNB Price' in html, 'BNB trace missing from chart HTML'
print('OK, chart HTML length:', len(html))
"
```

Expected: `OK, chart HTML length: <some large number>` with no traceback.

- [ ] **Step 7: Commit**

```bash
git add generate_dashboard.py
git commit -m "Add BNB price trace to the interactive dashboard macro chart"
```

---

### Task 5: Add live HYPE/BNB FDV stats under the Morning Brief

**Files:**
- Modify: `generate_dashboard.py:19` (constants), `generate_dashboard.py` (new functions after `fetch_usdc_float_series`, ~line 308), `generate_dashboard.py:772-945` (CSS), `generate_dashboard.py:948-1032` (`build_html` signature + section 02), `generate_dashboard.py:1034-1064` (`main`)

**Interfaces:**
- Consumes: nothing from earlier tasks (independent CoinGecko fetch).
- Produces: `fetch_coin_market_stats(coin_id: str) -> dict` with keys `"price"` and `"fdv"` (each `float | None`); `build_fdv_stats_html(hype_stats: dict, bnb_stats: dict) -> str`; `build_html(...)` gains a new required parameter `fdv_stats_html: str` (last positional/keyword parameter).

- [ ] **Step 1: Add the CoinGecko coin-id constant**

In `generate_dashboard.py`, change:

```python
STABLECOIN_CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/Hyperliquid%20L1"
```

to:

```python
STABLECOIN_CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/Hyperliquid%20L1"
COINGECKO_COIN_IDS = {"hype": "hyperliquid", "bnb": "binancecoin"}
```

- [ ] **Step 2: Write `fetch_coin_market_stats`**

In `generate_dashboard.py`, right after the end of `fetch_usdc_float_series` (right before `def build_usdc_float_chart_html(df: pd.DataFrame) -> str:`), add:

```python
def fetch_coin_market_stats(coin_id: str) -> dict:
    """Fetch current USD price and fully-diluted valuation for a CoinGecko coin id.

    Returns {"price": float | None, "fdv": float | None}. On any failure both
    are None so the dashboard build can render a live-fetch failure
    gracefully (as an em dash in the UI) instead of crashing.
    """
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    params = {
        "localization": "false", "tickers": "false", "market_data": "true",
        "community_data": "false", "developer_data": "false", "sparkline": "false",
    }
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        market_data = resp.json()["market_data"]
        return {
            "price": market_data.get("current_price", {}).get("usd"),
            "fdv": market_data.get("fully_diluted_valuation", {}).get("usd"),
        }
    except Exception as exc:
        print(f"CoinGecko market stats fetch failed for {coin_id}: {exc}", file=sys.stderr)
        return {"price": None, "fdv": None}
```

- [ ] **Step 3: Write `build_fdv_stats_html`**

In `generate_dashboard.py`, right after `fetch_coin_market_stats`, add:

```python
def build_fdv_stats_html(hype_stats: dict, bnb_stats: dict) -> str:
    """Render a small live stat row: HYPE/BNB price + fully-diluted valuation.

    Supplements the brief's own static, once-daily Valuation table with a
    couple of live-refreshed CoinGecko figures. Missing values (fetch
    failure) render as an em dash rather than raising.
    """
    def fmt_usd(v):
        if v is None:
            return "—"
        if v >= 1e9:
            return f"${v / 1e9:,.2f}B"
        if v >= 1e6:
            return f"${v / 1e6:,.1f}M"
        return f"${v:,.2f}"

    return f"""
    <div class="fdv-stats">
      <div class="estimate-flag">LIVE &middot; CoinGecko</div>
      <div class="readout-grid">
        <div class="readout-card"><div class="lbl">HYPE Price</div><div class="val">{fmt_usd(hype_stats['price'])}</div></div>
        <div class="readout-card"><div class="lbl">HYPE FDV</div><div class="val">{fmt_usd(hype_stats['fdv'])}</div></div>
        <div class="readout-card"><div class="lbl">BNB Price</div><div class="val">{fmt_usd(bnb_stats['price'])}</div></div>
        <div class="readout-card"><div class="lbl">BNB FDV</div><div class="val">{fmt_usd(bnb_stats['fdv'])}</div></div>
      </div>
    </div>
"""
```

- [ ] **Step 4: Add a small CSS spacing rule**

In `generate_dashboard.py`, inside the `CSS` string, change:

```python
.brief-card blockquote p { margin: 0; color: var(--ink-3); }
```

to:

```python
.brief-card blockquote p { margin: 0; color: var(--ink-3); }
.fdv-stats { margin-top: 14px; }
```

- [ ] **Step 5: Thread `fdv_stats_html` through `build_html`**

In `generate_dashboard.py`, change the function signature:

```python
def build_html(title: str, body_html: str, chart_html: str, brief_path: Path,
               row_count: int, usdc_float_chart_html: str, usdc_estimate_html: str,
               ps_explorer_html: str) -> str:
```

to:

```python
def build_html(title: str, body_html: str, chart_html: str, brief_path: Path,
               row_count: int, usdc_float_chart_html: str, usdc_estimate_html: str,
               ps_explorer_html: str, fdv_stats_html: str) -> str:
```

And change section 02 from:

```python
  <section class="section">
    <div class="section-head">
      <span class="section-num">02</span>
      <h2 class="section-title">Morning Brief</h2>
    </div>
    <div class="brief-card">
{body_html}
    </div>
  </section>
```

to:

```python
  <section class="section">
    <div class="section-head">
      <span class="section-num">02</span>
      <h2 class="section-title">Morning Brief</h2>
    </div>
    <div class="brief-card">
{body_html}
    </div>
    {fdv_stats_html}
  </section>
```

- [ ] **Step 6: Wire it up in `main()`**

In `generate_dashboard.py`, change:

```python
    usdc_float_df = fetch_usdc_float_series()
    live_float_usd = float(usdc_float_df["circulating_usd"].iloc[-1]) if not usdc_float_df.empty else None
    usdc_float_chart_html = build_usdc_float_chart_html(usdc_float_df)
    usdc_estimate_html = build_usdc_estimate_html(live_float_usd)
    ps_explorer_html = build_ps_explorer_html(live_float_usd)

    html = build_html(title, body_html, chart_html, brief_path, len(df),
                       usdc_float_chart_html, usdc_estimate_html, ps_explorer_html)
```

to:

```python
    usdc_float_df = fetch_usdc_float_series()
    live_float_usd = float(usdc_float_df["circulating_usd"].iloc[-1]) if not usdc_float_df.empty else None
    usdc_float_chart_html = build_usdc_float_chart_html(usdc_float_df)
    usdc_estimate_html = build_usdc_estimate_html(live_float_usd)
    ps_explorer_html = build_ps_explorer_html(live_float_usd)

    hype_stats = fetch_coin_market_stats(COINGECKO_COIN_IDS["hype"])
    bnb_stats = fetch_coin_market_stats(COINGECKO_COIN_IDS["bnb"])
    fdv_stats_html = build_fdv_stats_html(hype_stats, bnb_stats)

    html = build_html(title, body_html, chart_html, brief_path, len(df),
                       usdc_float_chart_html, usdc_estimate_html, ps_explorer_html,
                       fdv_stats_html)
```

- [ ] **Step 7: Verify the FDV functions in isolation**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
source .venv/bin/activate
python3 -c "
from generate_dashboard import fetch_coin_market_stats, build_fdv_stats_html

hype = fetch_coin_market_stats('hyperliquid')
bnb = fetch_coin_market_stats('binancecoin')
print('HYPE:', hype)
print('BNB:', bnb)
assert hype['price'] is not None, 'HYPE price fetch failed'
assert bnb['price'] is not None, 'BNB price fetch failed'
html = build_fdv_stats_html(hype, bnb)
assert 'HYPE FDV' in html and 'BNB FDV' in html
print('OK')
"
```

Expected: printed dicts with plausible `price`/`fdv` numbers for both coins, then `OK`.

- [ ] **Step 8: Verify the fallback path renders `—` instead of crashing**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
python3 -c "
from generate_dashboard import build_fdv_stats_html
html = build_fdv_stats_html({'price': None, 'fdv': None}, {'price': None, 'fdv': None})
assert html.count('—') == 4
print('OK, fallback renders em dashes')
"
```

Expected: `OK, fallback renders em dashes`

- [ ] **Step 9: Run the full dashboard build end-to-end and inspect it in a browser**

```bash
cd /Users/elaineye/agent/hyperliquid_stats
source .venv/bin/activate
python generate_dashboard.py
```

Expected: `Dashboard written: .../dashboard.html` with no traceback.

```bash
grep -c "BNB Price" dashboard.html
grep -c "HYPE FDV" dashboard.html
open dashboard.html
```

In the opened browser tab, confirm visually:
- The macro chart (Section 01) shows a dashed teal BNB line at a sane price scale, with its own axis label on the far right, not visually colliding with the BTC/HYPE/P-S axes.
- Directly under the Morning Brief card (Section 02, below the Valuation table), a "LIVE · CoinGecko" stat row shows HYPE Price, HYPE FDV, BNB Price, and BNB FDV with plausible values.
- Hovering the BNB line on the chart shows a `BNB: $...` tooltip.

- [ ] **Step 10: Commit**

```bash
git add generate_dashboard.py
git commit -m "Add live HYPE/BNB FDV stats under the Morning Brief section"
```

---

## Self-Review Notes

- **Spec coverage:** Section 1 (schema) → Task 1. Section 2 (backfill) → Task 2. Section 3 (daily fetch) → Task 3. Section 4 (chart) → Task 4. Section 5 (FDV stats) → Task 5. Out-of-scope items (static PNG, brief markdown, chg columns) are explicitly not touched by any task.
- **Placeholder scan:** No TBD/TODO; every step has literal code or a literal shell command with expected output.
- **Type consistency:** `fetch_coin_market_stats` returns `{"price": ..., "fdv": ...}` in Task 5 Step 2, and `build_fdv_stats_html` (Step 3) and the verification steps (7, 8) consume exactly those two keys. `build_interactive_chart` (Task 4) reads `df["bnb_price"]`, which is selected by `load_metrics` in the same task's Step 1, populated by `upsert_daily`'s `record.get('bnb_price')` from Task 1, itself fed by `bnb_now` computed in Task 3. `build_html`'s new `fdv_stats_html` parameter (Task 5 Step 5) is passed positionally in `main()` (Task 5 Step 6) in matching order.
