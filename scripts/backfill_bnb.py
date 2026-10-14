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
