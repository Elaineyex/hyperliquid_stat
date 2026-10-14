# Hyperliquid Stats

View sample dashboard here: https://elaineyex.github.io/hyperliquid_stat/ 

Daily analytics pipeline for the Hyperliquid protocol: a `$HYPE` morning brief (price action, protocol revenue, valuation, market commentary), a 6-month macro trend chart, a row upserted into a local SQLite database, and an interactive HTML dashboard.

See `CLAUDE.md` for the full file-by-file breakdown and data-source notes.

## Project Layout

```
src/        Pipeline code: data fetch + DB write (plot_macro_trend.py), dashboard,
            revenue breakdown, and shared modules (db.py, aqa.py)
scripts/    Entry points: run_daily_report.sh (daily cron) and one-off DB backfills
docs/       Automation setup, data-source notes, reports, design specs
data/       SQLite database + backups (gitignored, local-only)
output/     Generated chart PNG and dashboard.html (gitignored)
logs/       Daily briefs, research notes, cron logs (gitignored)
index.html  Published GitHub Pages snapshot (must stay at repo root)
```

Run every command below from the repo root.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Daily Report

```bash
./scripts/run_daily_report.sh YYYY-MM-DD
```

If no date is passed, the script uses the current UTC date. This writes `logs/YYYY-MM-DD.md`, updates `output/hyperliquid_6m_macro_trend.png`, upserts that day's row in `data/hyperliquid_stats.db` (re-running a date overwrites it), and regenerates `output/dashboard.html` (last step, via `src/generate_dashboard.py`).

In production this runs automatically once a day via a macOS launchd job at **04:00 UTC** (12:00 Beijing time on the host Mac), which gives DefiLlama ~4 hours to settle the previous UTC day's revenue (see `docs/AUTOMATION.md`).

## Dashboard

```bash
python src/generate_dashboard.py [YYYY-MM-DD]
```

Builds `output/dashboard.html`: the interactive macro chart (including the headline P/S incl. AQAv2 line), the morning brief, a USDC reserve-income section, and an interactive $HYPE P/S explorer (drag price / AQA revenue / protocol revenue to see the valuation multiple move).

AQAv2 reserve income is cash paid monthly to the Assistance Fund and is not counted in DefiLlama's `revenue_daily`. The dashboard uses actual payouts read from the Assistance Fund ledger on the Hyperliquid API (`src/aqa.py`; first payout 2026-10-04). Only the Low/Base/High run-rate scenarios are estimates, computed from the live USDC float on DefiLlama.

`dashboard.html` is normally gitignored and regenerated fresh on each daily run rather than tracked — it's a point-in-time snapshot, not a versioned artifact. Regenerate it locally any time to get current numbers.

The `index.html` published in this repo (for GitHub Pages) is a one-off snapshot frozen on **2026-10-12** — it does not auto-update. To refresh it:

```bash
python src/generate_dashboard.py && cp output/dashboard.html index.html
git add index.html && git commit -m "Refresh published index.html snapshot" && git push
```

## Optional Revenue Breakdown

```bash
python src/generate_revenue_breakdown.py YYYY-MM-DD
```

Deep-dive revenue breakdown by source, native vs. HIP-3 volume/revenue split, and HIP-3 builder-dex table. Kept separate from the daily runner so this heavier report is only generated when explicitly requested.

## Data

`data/hyperliquid_stats.db` (single table, `daily_metrics`, 2024-12-23 to present) is gitignored and local-only — not versioned. Each row is one UTC day; prices are that day's Hyperliquid 1d-candle closes, not a live snapshot at run time.

A fresh clone has no database. To rebuild it, run `python scripts/backfill_since_tge.py`, then `python scripts/backfill_pre_cg_window.py` (see `CLAUDE.md` for details).

Generated markdown reports, PNG charts, logs, caches, and other fetched-data snapshots are gitignored too.

---

Built with [Claude Code](https://claude.com/claude-code).
