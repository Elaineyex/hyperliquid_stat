#!/usr/bin/env python3
"""
Fetch 6 months of historical data from Hyperliquid SDK + DefiLlama
and backfill hyperliquid_stats.db in the same format as plot_macro_trend.py.
"""

import os
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from hyperliquid.info import Info
from hyperliquid.utils import constants
from db import init_db, upsert_daily

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = Path(SCRIPT_DIR) / "hyperliquid_stats.db"
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins/hyperliquid"
COINGECKO_MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/hyperliquid/market_chart"


def get_sdk_price_history(symbol):
    print(f"Fetching {symbol} price history from Hyperliquid SDK...")
    info = Info(constants.MAINNET_API_URL, skip_ws=True)

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=220)  # Extra buffer for 30d rolling

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    candles = info.candles_snapshot(name=symbol, interval="1d", startTime=start_ms, endTime=end_ms)
    data = []
    for c in candles:
        data.append({
            'date': pd.to_datetime(c['t'], unit='ms', utc=True),
            f'{symbol}_price': float(c['c'])
        })
    df = pd.DataFrame(data).set_index('date')
    print(f"  Got {len(df)} days of {symbol} data")
    return df


def get_protocol_revenue_history():
    print("Fetching Protocol Revenue from DefiLlama...")
    url = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&dataType=dailyRevenue"
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = resp.json()
    processed = []
    for item in data['totalDataChart']:
        processed.append({
            'date': pd.to_datetime(item[0], unit='s', utc=True),
            'revenue': float(item[1])
        })
    df = pd.DataFrame(processed).set_index('date')
    print(f"  Got {len(df)} days of revenue data")
    return df


def get_hype_market_data_history():
    print("Fetching HYPE historical market cap from CoinGecko...")
    params = {
        "vs_currency": "usd",
        "days": "220",
        "interval": "daily",
    }
    resp = requests.get(COINGECKO_MARKET_CHART_URL, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    price_rows = {
        pd.to_datetime(item[0], unit='ms', utc=True).normalize(): float(item[1])
        for item in data.get('prices', [])
    }
    market_cap_rows = {
        pd.to_datetime(item[0], unit='ms', utc=True).normalize(): float(item[1])
        for item in data.get('market_caps', [])
    }

    processed = []
    for dt in sorted(set(price_rows) & set(market_cap_rows)):
        price = price_rows[dt]
        market_cap = market_cap_rows[dt]
        if price <= 0:
            continue
        processed.append({
            'date': dt,
            'cg_hype_price': price,
            'hype_market_cap': market_cap,
            'hype_circulating_supply': market_cap / price,
        })

    df = pd.DataFrame(processed).set_index('date')
    print(f"  Got {len(df)} days of HYPE market cap data")
    return df


def get_hype_total_supply():
    print("Fetching HYPE max supply from CoinGecko...")
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false",
        "sparkline": "false",
    }
    resp = requests.get(COINGECKO_COIN_URL, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    resp.raise_for_status()
    market_data = resp.json()['market_data']
    return float(market_data.get('max_supply') or market_data['total_supply'])


def build_metrics(hype_df, btc_df, rev_df):
    df = pd.merge(hype_df, btc_df, left_index=True, right_index=True, how='inner')
    df = pd.merge(df, rev_df, left_index=True, right_index=True, how='inner')
    df = df.sort_index()

    # Rolling revenue stats (computed on full series for accuracy)
    df['revenue_7d_avg'] = df['revenue'].rolling(window=7).mean()
    df['revenue_30d_avg'] = df['revenue'].rolling(window=30).mean()
    df['revenue_7d_vs_30d'] = (df['revenue_7d_avg'] / df['revenue_30d_avg'] - 1) * 100

    # Price % changes (shifted)
    for sym in ['HYPE', 'BTC']:
        col = f'{sym}_price'
        df[f'{sym}_1d_chg'] = (df[col] / df[col].shift(1) - 1) * 100
        df[f'{sym}_7d_chg'] = (df[col] / df[col].shift(7) - 1) * 100
        df[f'{sym}_30d_chg'] = (df[col] / df[col].shift(30) - 1) * 100

    # Filter to last 180 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    df = df[df.index >= cutoff].dropna(subset=['HYPE_price', 'BTC_price', 'revenue'])

    return df


def add_valuation_metrics(df, market_df, total_supply):
    df = pd.merge(df, market_df, left_index=True, right_index=True, how='left')
    df['hype_total_supply'] = total_supply
    df['hype_circulating_pct'] = (df['hype_circulating_supply'] / total_supply) * 100
    df['hype_ps_ratio'] = df['hype_market_cap'] / (df['revenue_7d_avg'] * 365)
    return df


def main():
    hype_df = get_sdk_price_history("HYPE")
    btc_df = get_sdk_price_history("BTC")
    rev_df = get_protocol_revenue_history()
    market_df = get_hype_market_data_history()
    total_supply = get_hype_total_supply()

    df = build_metrics(hype_df, btc_df, rev_df)
    df = add_valuation_metrics(df, market_df, total_supply)
    print(f"\nBuilt {len(df)} rows spanning {df.index[0].date()} → {df.index[-1].date()}")

    init_db(DB_PATH)
    inserted = 0
    for ts, row in df.iterrows():
        date_str = ts.strftime('%Y-%m-%d')
        record = {
            'date': date_str,
            'hype_price': row['HYPE_price'],
            'hype_1d_chg': row.get('HYPE_1d_chg'),
            'hype_7d_chg': row.get('HYPE_7d_chg'),
            'hype_30d_chg': row.get('HYPE_30d_chg'),
            'btc_price': row['BTC_price'],
            'btc_1d_chg': row.get('BTC_1d_chg'),
            'btc_7d_chg': row.get('BTC_7d_chg'),
            'btc_30d_chg': row.get('BTC_30d_chg'),
            'revenue_daily': row['revenue'],
            'revenue_7d_avg': row.get('revenue_7d_avg'),
            'revenue_30d_avg': row.get('revenue_30d_avg'),
            'revenue_7d_vs_30d': row.get('revenue_7d_vs_30d'),
            'hype_circulating_supply': row.get('hype_circulating_supply'),
            'hype_total_supply': row.get('hype_total_supply'),
            'hype_circulating_pct': row.get('hype_circulating_pct'),
            'hype_market_cap': row.get('hype_market_cap'),
            'hype_ps_ratio': row.get('hype_ps_ratio'),
        }
        upsert_daily(DB_PATH, record)
        inserted += 1

    print(f"Done — {inserted} rows upserted into {DB_PATH}")


if __name__ == "__main__":
    main()
