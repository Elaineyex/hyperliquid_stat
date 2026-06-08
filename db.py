import sqlite3
from datetime import datetime
from pathlib import Path


def init_db(db_path: Path):
    """Initialize the database and create the daily_metrics table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_metrics (
            date             TEXT PRIMARY KEY,
            hype_price       REAL,
            hype_1d_chg      REAL,
            hype_7d_chg      REAL,
            hype_30d_chg     REAL,
            btc_price        REAL,
            btc_1d_chg       REAL,
            btc_7d_chg       REAL,
            btc_30d_chg      REAL,
            revenue_daily    REAL,
            revenue_7d_avg   REAL,
            revenue_30d_avg  REAL,
            revenue_7d_vs_30d REAL,
            hype_circulating_supply REAL,
            hype_total_supply REAL,
            hype_circulating_pct REAL,
            hype_market_cap REAL,
            hype_ps_ratio REAL,
            created_at       TEXT
        )
    """)

    for column_name in (
        "hype_circulating_supply",
        "hype_total_supply",
        "hype_circulating_pct",
        "hype_market_cap",
        "hype_ps_ratio",
    ):
        try:
            cursor.execute(f"ALTER TABLE daily_metrics ADD COLUMN {column_name} REAL")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

    conn.commit()
    conn.close()


def upsert_daily(db_path: Path, record: dict):
    """Insert or replace a daily metrics record."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Add created_at timestamp if not provided
    if 'created_at' not in record:
        record['created_at'] = datetime.utcnow().isoformat()

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

    conn.commit()
    conn.close()
