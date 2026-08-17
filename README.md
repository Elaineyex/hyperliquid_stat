# Hyperliquid Stats

Daily analytics pipeline for the Hyperliquid protocol: a `$HYPE` morning brief (price action, protocol revenue, valuation, market commentary), a 6-month macro trend chart, a row appended to a tracked SQLite database, and an interactive HTML dashboard.

See `CLAUDE.md` for the full file-by-file breakdown and data-source notes.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Daily Report

```bash
./run_daily_report.sh YYYY-MM-DD
```

If no date is passed, the script uses the current UTC date. This writes `logs/YYYY-MM-DD.md`, updates `hyperliquid_6m_macro_trend.png`, appends a row to `hyperliquid_stats.db`, and regenerates `dashboard.html` (last step, via `generate_dashboard.py`).

In production this runs automatically once a day via a macOS launchd job at 12:00 local time (see `AUTOMATION.md`).

## Dashboard

```bash
python generate_dashboard.py [YYYY-MM-DD]
```

Builds `dashboard.html`: the interactive macro chart, the morning brief, a live USDC-float chart + AQA/AQAv2 stablecoin reserve-income estimate (DefiLlama-sourced, off-protocol revenue not reflected in `revenue_daily`), and an interactive $HYPE P/S explorer (drag price / AQA revenue / protocol revenue to see the valuation multiple move).

`dashboard.html` is normally gitignored and regenerated fresh on each daily run rather than tracked — it's a point-in-time snapshot, not a versioned artifact. Regenerate it locally any time to get current numbers.

## Optional Revenue Breakdown

```bash
python generate_revenue_breakdown.py YYYY-MM-DD
```

Deep-dive revenue breakdown by source, native vs. HIP-3 volume/revenue split, and HIP-3 builder-dex table. Kept separate from the daily runner so this heavier report is only generated when explicitly requested.

## Data

`hyperliquid_stats.db` (single table, `daily_metrics`, 2024-12-23 to present) is gitignored and local-only — not versioned. Generated markdown reports, PNG charts, logs, caches, and other fetched-data snapshots are gitignored too.
