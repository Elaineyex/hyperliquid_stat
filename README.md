# Hyperliquid Stats

Daily Hyperliquid analytics scripts for generating a `$HYPE` morning brief with price action, protocol revenue, valuation, and summary commentary.

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

If no date is passed, the script uses the current UTC date. Generated markdown reports, charts, local databases, logs, caches, and fetched data snapshots are intentionally ignored by Git.

## Optional Revenue Breakdown

```bash
python generate_revenue_breakdown.py YYYY-MM-DD
```

The breakdown script is kept separate from the daily runner so contributor reports are only generated when explicitly requested.

