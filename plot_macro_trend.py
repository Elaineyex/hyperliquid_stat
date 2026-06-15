import os
import sys
import json
import sqlite3
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from hyperliquid.info import Info
from hyperliquid.utils import constants
from db import init_db, upsert_daily

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = Path(SCRIPT_DIR) / "hyperliquid_stats.db"
CACHE_DIR = Path(SCRIPT_DIR) / ".cache"
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins/hyperliquid"
COINGECKO_MARKET_CHART_URL = "https://api.coingecko.com/api/v3/coins/hyperliquid/market_chart"
HIP4_PREDICTION_FEE_RATE = float(os.environ.get("HIP4_PREDICTION_FEE_RATE", "0"))

target_date = datetime.now(timezone.utc)
if len(sys.argv) > 1:
    target_date = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)

def get_sdk_price_history(symbol):
    print(f"Fetching {symbol} price history from Hyperliquid...")
    
    end_time = target_date
    start_time = end_time - timedelta(days=200) # Extra buffer
    
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    try:
        candles = fetch_hl_info({
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": "1d",
                "startTime": start_ms,
                "endTime": end_ms,
            },
        })
        data = []
        for c in candles:
            data.append({
                'date': pd.to_datetime(c['t'], unit='ms', utc=True),
                f'{symbol}_price': float(c['c'])
            })
        df = pd.DataFrame(data).set_index('date')
        return df
    except Exception as e:
        print(f"Failed to fetch {symbol}: {e}")
        return None

def get_estimated_revenue_from_hl():
    try:
        resp_perps = requests.post(HL_INFO_URL, json={"type": "metaAndAssetCtxs"})
        ctxs_perps = resp_perps.json()[1]
        perp_vol = sum(float(c["dayNtlVlm"]) for c in ctxs_perps)
        
        resp_spot = requests.post(HL_INFO_URL, json={"type": "spotMetaAndAssetCtxs"})
        ctxs_spot = resp_spot.json()[1]
        spot_vol = sum(float(c["dayNtlVlm"]) for c in ctxs_spot)
        
        return (perp_vol * 0.00035) + (spot_vol * 0.00010)
    except Exception as e:
        print(f"Failed to fetch HL estimated revenue: {e}")
        return None


def fetch_hl_info(payload):
    response = requests.post(HL_INFO_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_json_with_retries(url, params=None, attempts=3):
    import time

    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            last_error = e
            if attempt < attempts - 1:
                sleep_seconds = 15 if "429" in str(e) else 2
                time.sleep(sleep_seconds)

    raise last_error


def fetch_hype_market_chart(days=220):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"coingecko_hype_market_chart_{days}.json"
    max_cache_age_seconds = 60 * 60

    if cache_path.exists():
        cache_age = datetime.now(timezone.utc).timestamp() - cache_path.stat().st_mtime
        if cache_age <= max_cache_age_seconds:
            with open(cache_path, "r", encoding="utf-8") as handle:
                return json.load(handle)

    params = {
        "vs_currency": "usd",
        "days": str(days),
        "interval": "daily",
    }
    data = fetch_json_with_retries(COINGECKO_MARKET_CHART_URL, params=params)
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return data


def get_hype_market_data():
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false",
        "sparkline": "false",
    }
    return fetch_json_with_retries(COINGECKO_COIN_URL, params=params)["market_data"]


def get_hype_supply_denominator(market_data):
    total_supply = market_data.get("max_supply") or market_data.get("total_supply")
    if total_supply is None:
        raise ValueError("CoinGecko did not return max_supply or total_supply for HYPE")
    return float(total_supply)


def build_hype_valuation(revenue_7d_avg, circulating_supply, total_supply, market_cap):
    circulating_supply = float(circulating_supply)
    total_supply = float(total_supply)
    market_cap = float(market_cap)
    circulating_pct = circulating_supply / total_supply * 100
    ps_ratio = market_cap / (revenue_7d_avg * 365)

    return {
        "circulating_supply": circulating_supply,
        "total_supply": total_supply,
        "circulating_pct": circulating_pct,
        "market_cap": market_cap,
        "ps_ratio": ps_ratio,
    }


def get_latest_cached_valuation_inputs(current_hype_price=None):
    if not DB_PATH.exists():
        raise ValueError(f"No local valuation cache found at {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date, hype_circulating_supply, hype_total_supply, hype_market_cap
            FROM daily_metrics
            WHERE hype_circulating_supply IS NOT NULL
              AND hype_total_supply IS NOT NULL
              AND hype_market_cap IS NOT NULL
            ORDER BY date DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
    finally:
        conn.close()

    if row is None:
        raise ValueError("No cached valuation inputs found in daily_metrics")

    cached_date, circulating_supply, total_supply, cached_market_cap = row
    market_cap = float(cached_market_cap)
    if current_hype_price is not None:
        market_cap = float(current_hype_price) * float(circulating_supply)

    return {
        "date": cached_date,
        "circulating_supply": float(circulating_supply),
        "total_supply": float(total_supply),
        "market_cap": market_cap,
    }


def get_current_hype_valuation(revenue_7d_avg, current_hype_price=None):
    print("Fetching current HYPE valuation metrics from CoinGecko...")
    try:
        market_data = get_hype_market_data()
        return build_hype_valuation(
            revenue_7d_avg,
            market_data["circulating_supply"],
            get_hype_supply_denominator(market_data),
            market_data["market_cap"]["usd"],
        )
    except Exception as e:
        print(f"CoinGecko current valuation fetch failed, using cached supply fallback: {e}")
        cached = get_latest_cached_valuation_inputs(current_hype_price)
        valuation = build_hype_valuation(
            revenue_7d_avg,
            cached["circulating_supply"],
            cached["total_supply"],
            cached["market_cap"],
        )
        valuation["date"] = f"{target_date.strftime('%Y-%m-%d')} (supply cached from {cached['date']})"
        return valuation


def get_historical_hype_valuation(revenue_7d_avg, valuation_date):
    valuation_day = pd.Timestamp(valuation_date.date(), tz="UTC")
    print(f"Fetching HYPE valuation metrics from CoinGecko for {valuation_day.strftime('%Y-%m-%d')}...")

    market_data = get_hype_market_data()
    total_supply = get_hype_supply_denominator(market_data)

    data = fetch_hype_market_chart(days=220)

    price_rows = {
        pd.to_datetime(item[0], unit='ms', utc=True).normalize(): float(item[1])
        for item in data.get("prices", [])
    }
    market_cap_rows = {
        pd.to_datetime(item[0], unit='ms', utc=True).normalize(): float(item[1])
        for item in data.get("market_caps", [])
    }

    if valuation_day not in price_rows or valuation_day not in market_cap_rows:
        raise ValueError(f"Missing HYPE CoinGecko market data for {valuation_day.strftime('%Y-%m-%d')}")

    price = price_rows[valuation_day]
    market_cap = market_cap_rows[valuation_day]
    if price <= 0:
        raise ValueError(f"Invalid HYPE CoinGecko price for {valuation_day.strftime('%Y-%m-%d')}: {price}")

    return build_hype_valuation(revenue_7d_avg, market_cap / price, total_supply, market_cap)


def get_hype_valuation(revenue_7d_avg, valuation_date, current_hype_price=None):
    today_utc = datetime.now(timezone.utc).date()
    if valuation_date.date() >= today_utc:
        valuation = get_current_hype_valuation(revenue_7d_avg, current_hype_price)
    else:
        valuation = get_historical_hype_valuation(revenue_7d_avg, valuation_date)
    if "date" not in valuation:
        valuation["date"] = valuation_date.strftime("%Y-%m-%d")
    return valuation


def get_hype_market_chart_history(days=220):
    data = fetch_hype_market_chart(days=days)

    processed = []
    for item in data.get("market_caps", []):
        processed.append({
            "date": pd.to_datetime(item[0], unit='ms', utc=True).normalize(),
            "hype_market_cap": float(item[1]),
        })

    if not processed:
        return pd.DataFrame(columns=["hype_market_cap"])

    return pd.DataFrame(processed).drop_duplicates("date").set_index("date").sort_index()


def get_hip4_prediction_market_revenue_history():
    print("Fetching HIP-4 Prediction Market Revenue from Hyperliquid...")
    try:
        outcome_meta = fetch_hl_info({"type": "outcomeMeta"})
        outcomes = outcome_meta.get("outcomes", [])
        if not outcomes:
            print("  No active HIP-4 outcome markets found.")
            return pd.DataFrame(columns=["hip4_prediction_volume", "hip4_prediction_revenue"])

        start_time = target_date - timedelta(days=200)
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(target_date.timestamp() * 1000)
        daily_totals = {}
        outcome_coins = []

        for outcome in outcomes:
            outcome_id = int(outcome["outcome"])
            side_specs = outcome.get("sideSpecs", [])
            for side in range(len(side_specs)):
                encoding = outcome_id * 10 + side
                coin = f"#{encoding}"
                outcome_coins.append(coin)
                candles = fetch_hl_info({
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                        "interval": "1d",
                        "startTime": start_ms,
                        "endTime": end_ms,
                    },
                })
                for candle in candles:
                    dt = pd.to_datetime(candle["t"], unit="ms", utc=True)
                    volume = float(candle.get("v", 0) or 0)
                    daily_totals[dt] = daily_totals.get(dt, 0.0) + volume

        processed = []
        for dt, volume in daily_totals.items():
            processed.append({
                "date": dt,
                "hip4_prediction_volume": volume,
                "hip4_prediction_revenue": volume * HIP4_PREDICTION_FEE_RATE,
            })

        df = pd.DataFrame(processed)
        if df.empty:
            df = pd.DataFrame(columns=["date", "hip4_prediction_volume", "hip4_prediction_revenue"])
        df = df.set_index("date").sort_index()
        print(
            f"  Found {len(outcomes)} active outcome market(s), {len(outcome_coins)} side coin(s); "
            f"HIP-4 fee rate {HIP4_PREDICTION_FEE_RATE:.4%}"
        )
        return df
    except Exception as e:
        print(f"Failed to fetch HIP-4 prediction market revenue: {e}")
        return None


def get_protocol_revenue_history():
    print("Fetching Protocol Revenue from DefiLlama (excluding Spectra V2)...")
    url_hl = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&dataType=dailyRevenue"
    url_spectra = "https://api.llama.fi/summary/fees/spectra-v2?dataType=dailyRevenue"
    
    try:
        import time
        for attempt in range(3):
            try:
                # Fetch HL Total
                resp_hl = requests.get(url_hl, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
                data_hl = resp_hl.json()
                
                # Fetch Spectra V2 (to subtract)
                resp_spectra = requests.get(url_spectra, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
                data_spectra = resp_spectra.json()
                break
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt == 2:
                    return None
                time.sleep(2)
        
        if 'totalDataChart' in data_hl:
            chart_hl = {pd.to_datetime(item[0], unit='s', utc=True): float(item[1]) for item in data_hl['totalDataChart']}
            breakdown_hl = {}
            for item in data_hl.get('totalDataChartBreakdown', []):
                dt = pd.to_datetime(item[0], unit='s', utc=True)
                breakdown_hl[dt] = sum(float(value) for value in item[1].values())
            
            # Spectra data
            spectra_chart = {}
            if 'totalDataChart' in data_spectra:
                spectra_chart = {pd.to_datetime(item[0], unit='s', utc=True): float(item[1]) for item in data_spectra['totalDataChart']}
            
            processed = []
            for dt, rev in chart_hl.items():
                breakdown_rev = breakdown_hl.get(dt)
                if breakdown_rev is not None and breakdown_rev > rev * 1.25:
                    print(
                        f"  DefiLlama aggregate revenue for {dt.strftime('%Y-%m-%d')} "
                        f"looks incomplete (${rev:,.0f}); using source breakdown sum ${breakdown_rev:,.0f}."
                    )
                    rev = breakdown_rev
                spectra_rev = spectra_chart.get(dt, 0)
                # Subtract Spectra revenue if present
                net_rev = max(0, rev - spectra_rev)
                if dt <= target_date:
                    processed.append({
                        'date': dt,
                        'revenue': net_rev
                    })
            
            df = pd.DataFrame(processed).set_index('date').sort_index()
            hip4_df = get_hip4_prediction_market_revenue_history()
            if hip4_df is None:
                print("  Skipping HIP-4 prediction market revenue due to fetch failure.")
                hip4_df = pd.DataFrame(columns=["hip4_prediction_volume", "hip4_prediction_revenue"])

            if not hip4_df.empty:
                df = pd.merge(df, hip4_df, left_index=True, right_index=True, how='outer')
                df['revenue'] = df['revenue'].fillna(0) + df['hip4_prediction_revenue'].fillna(0)
                df = df[['revenue']].sort_index()
            
            return df
        return None
    except Exception as e:
        print(f"Failed to fetch revenue: {e}")
        return None


def get_revenue_metrics(revenue_df, revenue_date):
    revenue_day = pd.Timestamp(revenue_date.date(), tz="UTC")
    prev_day = revenue_day - pd.Timedelta(days=1)
    revenue_df = revenue_df.sort_index()

    if revenue_day not in revenue_df.index:
        latest_available = "none"
        if not revenue_df.empty:
            latest_available = revenue_df.index.max().strftime("%Y-%m-%d")
        raise ValueError(
            f"Missing complete revenue data for {revenue_day.strftime('%Y-%m-%d')} "
            f"(latest available: {latest_available})"
        )

    if prev_day not in revenue_df.index:
        raise ValueError(f"Missing previous revenue data for {prev_day.strftime('%Y-%m-%d')}")

    revenue_window = revenue_df[revenue_df.index <= revenue_day]
    latest_rev = revenue_window.loc[revenue_day, "revenue"]
    prev_rev = revenue_window.loc[prev_day, "revenue"]
    rev_7d_avg = revenue_window["revenue"].tail(7).mean()
    rev_30d_avg = revenue_window["revenue"].tail(30).mean()
    rev_7d_vs_30d = (rev_7d_avg / rev_30d_avg - 1) * 100

    return {
        "date": revenue_day.strftime("%Y-%m-%d"),
        "latest_rev": float(latest_rev),
        "prev_rev": float(prev_rev),
        "rev_7d_avg": float(rev_7d_avg),
        "rev_30d_avg": float(rev_30d_avg),
        "rev_7d_vs_30d": float(rev_7d_vs_30d),
    }


def plot_combined_data(hype_df, btc_df, revenue_df, market_cap_df=None):
    print("Generating 6-month multi-asset plot...")
    
    # Merge all
    df = pd.merge(hype_df, btc_df, left_index=True, right_index=True, how='inner')
    df = pd.merge(df, revenue_df, left_index=True, right_index=True, how='inner')
    if market_cap_df is not None and not market_cap_df.empty:
        df = pd.merge(df, market_cap_df, left_index=True, right_index=True, how='left')
    
    # Filter last 180 days
    cutoff = target_date - timedelta(days=180)
    df = df[df.index >= cutoff]
    
    if df.empty:
        print("No data overlap found.")
        return

    # Calculate 7d avg for revenue
    df['revenue_7d_avg'] = df['revenue'].rolling(window=7).mean()
    if 'hype_market_cap' in df.columns:
        df['hype_ps_ratio'] = df['hype_market_cap'] / (df['revenue_7d_avg'] * 365)

    # Create Plot with multiple Y-axes
    fig, ax1 = plt.subplots(figsize=(15, 8))
    plt.subplots_adjust(right=0.80) # Make room for right-side axes

    # Axis 1: Revenue (Left)
    color_rev = '#1f77b4' # Blue
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Daily Revenue (USD)', color=color_rev, fontsize=11, fontweight='bold')
    ax1.plot(df.index, df['revenue'], color=color_rev, alpha=0.2, label='Daily Revenue')
    ax1.plot(df.index, df['revenue_7d_avg'], color=color_rev, linewidth=2, label='Revenue (7d Avg)')
    ax1.tick_params(axis='y', labelcolor=color_rev)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1e6:.1f}M' if x >= 1e6 else f'${x:,.0f}'))
    ax1.grid(True, which='both', linestyle='--', alpha=0.3)

    # Axis 2: HYPE Price (Right)
    ax2 = ax1.twinx()
    color_hype = '#2ca02c' # Green
    ax2.set_ylabel('HYPE Price (USD)', color=color_hype, fontsize=11, fontweight='bold')
    ax2.plot(df.index, df['HYPE_price'], color=color_hype, linewidth=2.5, label='HYPE Price')
    ax2.tick_params(axis='y', labelcolor=color_hype)

    # Axis 3: BTC Price (Right - Offset)
    ax3 = ax1.twinx()
    # Offset the right spine of ax3
    ax3.spines['right'].set_position(('outward', 60))
    color_btc = '#ff7f0e' # Orange
    ax3.set_ylabel('BTC Price (USD)', color=color_btc, fontsize=11, fontweight='bold')
    ax3.plot(df.index, df['BTC_price'], color=color_btc, linewidth=1.5, linestyle=':', label='BTC Price')
    ax3.tick_params(axis='y', labelcolor=color_btc)
    ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x/1e3:.0f}k'))

    ax4 = None
    if 'hype_ps_ratio' in df.columns and df['hype_ps_ratio'].notna().any():
        ax4 = ax1.twinx()
        ax4.spines['right'].set_position(('outward', 120))
        color_ps = '#9467bd' # Purple
        ax4.set_ylabel('HYPE P/S (7d revenue annualized)', color=color_ps, fontsize=11, fontweight='bold')
        ax4.plot(df.index, df['hype_ps_ratio'], color=color_ps, linewidth=2, linestyle='-.', label='HYPE P/S')
        ax4.tick_params(axis='y', labelcolor=color_ps)
        ax4.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.0f}x'))

    # X-axis formatting
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=0)

    # Title and Legend
    plt.title('Hyperliquid 6-Month Macro Trend: Revenue, $HYPE, BTC, and P/S', fontsize=14, pad=25)
    
    # Consolidate legends
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    h3, l3 = ax3.get_legend_handles_labels()
    handles = h1 + h2 + h3
    labels = l1 + l2 + l3
    if ax4 is not None:
        h4, l4 = ax4.get_legend_handles_labels()
        handles += h4
        labels += l4
    ax1.legend(handles, labels, loc='upper left', frameon=True, shadow=True)

    plt.tight_layout()
    
    output_name = os.path.join(SCRIPT_DIR, 'hyperliquid_6m_macro_trend.png')
    plt.savefig(output_name, dpi=150)
    print(f"Multi-asset chart saved as: {output_name}")

if __name__ == "__main__":
    hype_df = get_sdk_price_history("HYPE")
    btc_df = get_sdk_price_history("BTC")
    rev_df = get_protocol_revenue_history()

    if all(d is not None for d in [hype_df, btc_df, rev_df]):
        report_date = target_date
        revenue_date = report_date - timedelta(days=1)
        try:
            revenue_metrics = get_revenue_metrics(rev_df, revenue_date)
        except ValueError as e:
            print(e)
            sys.exit(1)

        revenue_day = revenue_metrics["date"]
        print(f"\n{'='*50}")
        print(f"  Hyperliquid Daily Summary  {revenue_day}")
        print(f"{'='*50}")

        hype_now  = hype_df['HYPE_price'].iloc[-1]
        hype_prev = hype_df['HYPE_price'].iloc[-2]
        hype_7d   = hype_df['HYPE_price'].iloc[-8] if len(hype_df) >= 8 else hype_df['HYPE_price'].iloc[0]
        hype_30d  = hype_df['HYPE_price'].iloc[-31] if len(hype_df) >= 31 else hype_df['HYPE_price'].iloc[0]
        hype_1d_chg = (hype_now/hype_prev-1)*100
        hype_7d_chg = (hype_now/hype_7d-1)*100
        hype_30d_chg = (hype_now/hype_30d-1)*100
        print(f"HYPE Price:    ${hype_now:.2f}  ({hype_1d_chg:+.1f}% 1d | {hype_7d_chg:+.1f}% 7d | {hype_30d_chg:+.1f}% 30d)")

        btc_now  = btc_df['BTC_price'].iloc[-1]
        btc_prev = btc_df['BTC_price'].iloc[-2]
        btc_7d   = btc_df['BTC_price'].iloc[-8] if len(btc_df) >= 8 else btc_df['BTC_price'].iloc[0]
        btc_30d  = btc_df['BTC_price'].iloc[-31] if len(btc_df) >= 31 else btc_df['BTC_price'].iloc[0]
        btc_1d_chg = (btc_now/btc_prev-1)*100
        btc_7d_chg = (btc_now/btc_7d-1)*100
        btc_30d_chg = (btc_now/btc_30d-1)*100
        print(f"BTC Price:     ${btc_now:,.0f}  ({btc_1d_chg:+.1f}% 1d | {btc_7d_chg:+.1f}% 7d | {btc_30d_chg:+.1f}% 30d)")

        latest_rev  = revenue_metrics["latest_rev"]
        prev_rev    = revenue_metrics["prev_rev"]
        rev_7d_avg  = revenue_metrics["rev_7d_avg"]
        rev_30d_avg = revenue_metrics["rev_30d_avg"]
        rev_7d_vs_30d = revenue_metrics["rev_7d_vs_30d"]
        try:
            hype_valuation = get_hype_valuation(rev_7d_avg, target_date, hype_now)
        except Exception as e:
            print(f"Failed to fetch HYPE valuation metrics from CoinGecko: {e}")
            sys.exit(1)

        print(f"Daily Revenue: ${latest_rev:,.0f}  ({(latest_rev/prev_rev-1)*100:+.1f}% vs prev day)  [{revenue_day}]")
        print(f"  7d avg:      ${rev_7d_avg:,.0f}")
        print(f"  30d avg:     ${rev_30d_avg:,.0f}  (7d vs 30d: {rev_7d_vs_30d:+.1f}%)")
        print(f"HYPE Valuation: circulating {hype_valuation['circulating_pct']:.1f}% of {hype_valuation['total_supply']:,.0f} supply  [{hype_valuation['date']}]")
        print(f"  Market Cap:  ${hype_valuation['market_cap']:,.0f}")
        print(f"  P/S 7d ann:  {hype_valuation['ps_ratio']:.1f}x")

        print(f"{'='*50}\n")

        # Persist to database
        init_db(DB_PATH)
        upsert_daily(DB_PATH, {
            'date': revenue_day,
            'hype_price': float(hype_now),
            'hype_1d_chg': float(hype_1d_chg),
            'hype_7d_chg': float(hype_7d_chg),
            'hype_30d_chg': float(hype_30d_chg),
            'btc_price': float(btc_now),
            'btc_1d_chg': float(btc_1d_chg),
            'btc_7d_chg': float(btc_7d_chg),
            'btc_30d_chg': float(btc_30d_chg),
            'revenue_daily': float(latest_rev),
            'revenue_7d_avg': float(rev_7d_avg),
            'revenue_30d_avg': float(rev_30d_avg),
            'revenue_7d_vs_30d': float(rev_7d_vs_30d),
            'hype_circulating_supply': float(hype_valuation['circulating_supply']),
            'hype_total_supply': float(hype_valuation['total_supply']),
            'hype_circulating_pct': float(hype_valuation['circulating_pct']),
            'hype_market_cap': float(hype_valuation['market_cap']),
            'hype_ps_ratio': float(hype_valuation['ps_ratio'])
        })
        print(f"Metrics persisted to database: {DB_PATH}")

        try:
            market_cap_df = get_hype_market_chart_history()
        except Exception as e:
            print(f"Failed to fetch HYPE market cap history from CoinGecko: {e}")
            sys.exit(1)

        plot_combined_data(hype_df, btc_df, rev_df, market_cap_df)
    else:
        print("Failed to collect all data points.")
