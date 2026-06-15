#!/usr/bin/env python3
"""Fill the pre-2025-06-16 gap in HYPE market cap.

CoinGecko's free tier only returns the trailing 365 days, so HYPE TGE through
the start of our CG window (2024-12-23 → 2025-06-15) has no market_cap. This
script fills that gap by:

1. Pulling daily HYPE prices for the gap range from DefiLlama's coins API
   (which proxies historical CG without the 365-day window).
2. Approximating circulating supply as the earliest known CG supply value
   (~334M, from 2025-06-16). Pre-2025-06-16, the schedule shows team
   allocations had not yet unlocked, so circulating supply was relatively
   stable in the 270M-334M range. This is an approximation — flagged in the
   `created_at` column with a `_approx` suffix.
3. mcap = price * supply, then upserts only the rows currently NULL.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DB_PATH = Path(__file__).resolve().parent / "hyperliquid_stats.db"
DEFILLAMA_CHART = "https://coins.llama.fi/chart/coingecko:hyperliquid"


def fetch_defillama_prices(start_ts: int, span_days: int) -> pd.DataFrame:
    params = {"start": start_ts, "span": span_days, "period": "1d"}
    resp = requests.get(DEFILLAMA_CHART, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()["coins"]["coingecko:hyperliquid"]["prices"]
    rows = [
        {
            "date": pd.to_datetime(p["timestamp"], unit="s", utc=True).normalize(),
            "price": float(p["price"]),
        }
        for p in payload
    ]
    return pd.DataFrame(rows).drop_duplicates("date").set_index("date").sort_index()


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        gap_rows = conn.execute(
            "SELECT date FROM daily_metrics WHERE hype_market_cap IS NULL "
            "ORDER BY date ASC"
        ).fetchall()
        if not gap_rows:
            print("No rows missing market cap.")
            return 0

        gap_dates = [r[0] for r in gap_rows]
        first = pd.to_datetime(gap_dates[0])
        last = pd.to_datetime(gap_dates[-1])
        span = (last - first).days + 5
        print(f"Filling {len(gap_dates)} rows {first.date()} → {last.date()}")

        baseline = conn.execute(
            "SELECT hype_circulating_supply FROM daily_metrics "
            "WHERE hype_circulating_supply IS NOT NULL ORDER BY date ASC LIMIT 1"
        ).fetchone()
        if not baseline:
            print("No circulating-supply baseline found. Run backfill_since_tge first.")
            return 1
        supply_proxy = float(baseline[0])
        print(f"Using supply proxy: {supply_proxy:,.0f} HYPE "
              "(earliest CG observation)")

        prices = fetch_defillama_prices(int(first.timestamp()), span)
        time.sleep(0.5)
        print(f"DefiLlama returned {len(prices)} price rows")

        marker = f"approx_via_defillama:{datetime.now(timezone.utc).isoformat()}"
        updated = 0
        for date_str in gap_dates:
            ts = pd.Timestamp(date_str, tz="UTC")
            if ts not in prices.index:
                continue
            price = prices.loc[ts, "price"]
            mcap = price * supply_proxy
            conn.execute(
                "UPDATE daily_metrics SET "
                "hype_circulating_supply = ?, hype_total_supply = ?, "
                "hype_circulating_pct = ?, hype_market_cap = ?, "
                "hype_ps_ratio = CASE WHEN revenue_7d_avg > 0 "
                "THEN ? / (revenue_7d_avg * 365) ELSE NULL END, "
                "created_at = ? "
                "WHERE date = ?",
                (
                    supply_proxy, 1_000_000_000.0,
                    supply_proxy / 1_000_000_000.0 * 100,
                    mcap, mcap, marker, date_str,
                ),
            )
            updated += 1
        conn.commit()
        print(f"Updated {updated} rows with approximated market cap & P/S")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
