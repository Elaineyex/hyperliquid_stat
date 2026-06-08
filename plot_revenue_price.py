
import matplotlib.pyplot as plt
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
import time
from hyperliquid.info import Info
from hyperliquid.utils import constants

def get_hype_price_history():
    print("Fetching HYPE price history from Hyperliquid SDK...")
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    # Calculate time range (last 35 days to be safe for 30 days of data)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=35)
    
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    # Fetch candles
    # Symbol "HYPE" was confirmed in discovery
    candles = info.candles_snapshot(name="HYPE", interval="1d", startTime=start_ms, endTime=end_ms)
    
    # Process into DataFrame
    data = []
    for c in candles:
        # candle structure: {'t': 170..., 'T': 170..., 's': 'HYPE', 'i': '1d', 'o': '...', 'c': '...', 'h': '...', 'l': '...', 'v': '...', 'n': ...}
        # 'c' is close price
        ts = pd.to_datetime(c['t'], unit='ms', utc=True)
        price = float(c['c'])
        data.append({'date': ts, 'price': price})
        
    df = pd.DataFrame(data)
    df.set_index('date', inplace=True)
    return df

def get_protocol_revenue_history():
    print("Fetching Protocol Revenue from DefiLlama...")
    # Endpoint for daily revenue
    # We use the 'fees' endpoint which typically includes revenue
    url = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false&dataType=dailyRevenue"
    
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = resp.json()
        
        # Structure check
        # usually data['totalDataChart'] is a list of [timestamp, value]
        if 'totalDataChart' in data:
            chart_data = data['totalDataChart']
            processed_data = []
            for item in chart_data:
                # timestamp is usually seconds
                ts = pd.to_datetime(item[0], unit='s', utc=True)
                revenue = float(item[1])
                processed_data.append({'date': ts, 'revenue': revenue})
            
            df = pd.DataFrame(processed_data)
            df.set_index('date', inplace=True)
            return df
        else:
            print("Warning: 'totalDataChart' not found in DefiLlama response.")
            print("Keys:", data.keys())
            return None
            
    except Exception as e:
        print(f"Error fetching revenue: {e}")
        return None

def plot_data(price_df, revenue_df):
    print("Plotting data...")
    
    # Merge dataframes
    # Resample to daily to ensure alignment
    price_daily = price_df.resample('D').last()
    revenue_daily = revenue_df.resample('D').sum() # Revenue is flow, sum makes sense if granular, but usually it's already daily
    
    # Filter last 30 days
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    
    combined = pd.merge(price_daily, revenue_daily, left_index=True, right_index=True, how='inner')
    combined = combined[combined.index >= cutoff]
    
    if combined.empty:
        print("No combined data found for the last 30 days.")
        return

    # Plot
    fig, ax1 = plt.subplots(figsize=(12, 6))

    color = 'tab:blue'
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Daily Revenue (USD)', color=color)
    ax1.plot(combined.index, combined['revenue'], color=color, marker='o', label='Daily Revenue')
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.grid(True, linestyle='--', alpha=0.5)

    ax2 = ax1.twinx()  # instantiate a second axes that shares the same x-axis
    color = 'tab:green'
    ax2.set_ylabel('HYPE Price (USD)', color=color)  # we already handled the x-label with ax1
    ax2.plot(combined.index, combined['price'], color=color, linestyle='--', linewidth=2, label='HYPE Price')
    ax2.tick_params(axis='y', labelcolor=color)

    plt.title('Hyperliquid: Daily Protocol Revenue vs $HYPE Price (Last 30 Days)')
    fig.tight_layout()  # otherwise the right y-label is slightly clipped
    
    plt.savefig('hyperliquid_revenue_vs_price.png')
    print("Chart saved to hyperliquid_revenue_vs_price.png")

if __name__ == "__main__":
    price_df = get_hype_price_history()
    revenue_df = get_protocol_revenue_history()
    
    if revenue_df is None:
        print("Could not fetch revenue data. Aborting plot.")
    else:
        plot_data(price_df, revenue_df)
