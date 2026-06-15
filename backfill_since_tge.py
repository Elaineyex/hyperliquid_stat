#!/usr/bin/env python3
"""Backfill the DB with HYPE/BTC/revenue/market-cap data since the HYPE TGE.

TGE: 2024-11-29. We fetch:
- HYPE & BTC daily closes via Hyperliquid SDK (in chunks if needed)
- Hyperliquid protocol daily revenue from DefiLlama (full history)
- HYPE market cap / circulating supply from CoinGecko (paginated daily series)
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from db import init_db, upsert_daily

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "hyperliquid_stats.db"
TGE_DATE = datetime(2024, 11, 29, tzinfo=timezone.utc)
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins/hyperliquid"
COINGECKO_MARKET_CHART_URL = (
    "https://api.coingecko.com/api/v3/coins/hyperliquid/market_chart"
)


def _post_with_retry(url: str, payload: dict, attempts: int = 4) -> dict:
    last: Exception | None = None
    for i in range(attempts):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"POST {url} failed after {attempts} attempts: {last}")


def fetch_candles(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Call /info candleSnapshot directly. Chunk by 90 days to stay safe."""
    rows: list[dict] = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=90), end)
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": "1d",
                "startTime": int(chunk_start.timestamp() * 1000),
                "endTime": int(chunk_end.timestamp() * 1000),
            },
        }
        data = _post_with_retry(HL_INFO_URL, payload)
        for c in data:
            rows.append({
                "date": pd.to_datetime(c["t"], unit="ms", utc=True),
                f"{symbol}_price": float(c["c"]),
            })
        chunk_start = chunk_end
        time.sleep(0.5)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates("date").set_index("date").sort_index()
    print(f"  {symbol}: {len(df)} rows {df.index[0].date()} → {df.index[-1].date()}")
    return df


def fetch_revenue(start: datetime) -> pd.DataFrame:
    url = ("https://api.llama.fi/overview/fees/hyperliquid"
           "?excludeTotalDataChart=false&dataType=dailyRevenue")
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    rows = []
    for ts, val in data["totalDataChart"]:
        d = pd.to_datetime(ts, unit="s", utc=True)
        if d >= pd.Timestamp(start):
            rows.append({"date": d, "revenue": float(val)})
    df = pd.DataFrame(rows).set_index("date").sort_index()
    print(f"  revenue: {len(df)} rows {df.index[0].date()} → {df.index[-1].date()}")
    return df


def fetch_market_cap(start: datetime, end: datetime) -> pd.DataFrame:
    """CoinGecko public endpoint. Free tier caps history at 365 days,
    so request `days=365` (the max free-tier window)."""
    params = {"vs_currency": "usd", "days": "365"}
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    last: Exception | None = None
    for attempt in range(5):
        try:
            resp = requests.get(
                COINGECKO_MARKET_CHART_URL, params=params,
                headers=headers, timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                break
            last = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            last = e
        time.sleep(3 * (attempt + 1))
    else:
        print(f"  market cap fetch failed: {last}; skipping market cap / P/S")
        return pd.DataFrame(columns=["cg_hype_price", "hype_market_cap",
                                     "hype_circulating_supply"])

    prices = {pd.to_datetime(p[0], unit="ms", utc=True).normalize(): float(p[1])
              for p in data.get("prices", [])}
    mcaps = {pd.to_datetime(p[0], unit="ms", utc=True).normalize(): float(p[1])
             for p in data.get("market_caps", [])}

    rows = []
    for dt in sorted(set(prices) & set(mcaps)):
        price = prices[dt]
        if price <= 0:
            continue
        mcap = mcaps[dt]
        rows.append({
            "date": dt,
            "cg_hype_price": price,
            "hype_market_cap": mcap,
            "hype_circulating_supply": mcap / price,
        })
    df = pd.DataFrame(rows).set_index("date").sort_index()
    print(f"  cg market: {len(df)} rows {df.index[0].date()} → {df.index[-1].date()}")
    return df


def fetch_total_supply() -> float | None:
    params = {"localization": "false", "tickers": "false", "market_data": "true",
              "community_data": "false", "developer_data": "false", "sparkline": "false"}
    try:
        resp = requests.get(COINGECKO_COIN_URL, params=params,
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        md = resp.json()["market_data"]
        return float(md.get("max_supply") or md["total_supply"])
    except Exception as e:
        print(f"  total supply fetch failed: {e}; using 1e9 fallback")
        return 1_000_000_000.0


def build(hype: pd.DataFrame, btc: pd.DataFrame, rev: pd.DataFrame,
          market: pd.DataFrame, total_supply: float | None) -> pd.DataFrame:
    df = hype.join(btc, how="outer").join(rev, how="outer")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=["HYPE_price", "BTC_price", "revenue"])

    df["revenue_7d_avg"] = df["revenue"].rolling(7).mean()
    df["revenue_30d_avg"] = df["revenue"].rolling(30).mean()
    df["revenue_7d_vs_30d"] = (df["revenue_7d_avg"] / df["revenue_30d_avg"] - 1) * 100

    for sym in ("HYPE", "BTC"):
        col = f"{sym}_price"
        df[f"{sym}_1d_chg"] = (df[col] / df[col].shift(1) - 1) * 100
        df[f"{sym}_7d_chg"] = (df[col] / df[col].shift(7) - 1) * 100
        df[f"{sym}_30d_chg"] = (df[col] / df[col].shift(30) - 1) * 100

    if not market.empty:
        df = df.join(market, how="left")
    if total_supply:
        df["hype_total_supply"] = total_supply
        if "hype_circulating_supply" in df.columns:
            df["hype_circulating_pct"] = (df["hype_circulating_supply"] / total_supply) * 100
    if "hype_market_cap" in df.columns:
        df["hype_ps_ratio"] = df["hype_market_cap"] / (df["revenue_7d_avg"] * 365)
    return df


def main() -> int:
    end = datetime.now(timezone.utc)
    print(f"Backfilling {TGE_DATE.date()} → {end.date()}")

    hype = fetch_candles("HYPE", TGE_DATE, end)
    btc = fetch_candles("BTC", TGE_DATE, end)
    rev = fetch_revenue(TGE_DATE)
    market = fetch_market_cap(TGE_DATE, end)
    total_supply = fetch_total_supply()

    df = build(hype, btc, rev, market, total_supply)
    print(f"\nFinal: {len(df)} rows {df.index[0].date()} → {df.index[-1].date()}")

    init_db(DB_PATH)
    inserted = 0
    for ts, row in df.iterrows():
        record = {
            "date": ts.strftime("%Y-%m-%d"),
            "hype_price": row["HYPE_price"],
            "hype_1d_chg": row.get("HYPE_1d_chg"),
            "hype_7d_chg": row.get("HYPE_7d_chg"),
            "hype_30d_chg": row.get("HYPE_30d_chg"),
            "btc_price": row["BTC_price"],
            "btc_1d_chg": row.get("BTC_1d_chg"),
            "btc_7d_chg": row.get("BTC_7d_chg"),
            "btc_30d_chg": row.get("BTC_30d_chg"),
            "revenue_daily": row["revenue"],
            "revenue_7d_avg": row.get("revenue_7d_avg"),
            "revenue_30d_avg": row.get("revenue_30d_avg"),
            "revenue_7d_vs_30d": row.get("revenue_7d_vs_30d"),
            "hype_circulating_supply": row.get("hype_circulating_supply"),
            "hype_total_supply": row.get("hype_total_supply"),
            "hype_circulating_pct": row.get("hype_circulating_pct"),
            "hype_market_cap": row.get("hype_market_cap"),
            "hype_ps_ratio": row.get("hype_ps_ratio"),
        }
        upsert_daily(DB_PATH, record)
        inserted += 1

    print(f"Inserted/updated {inserted} rows in {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
