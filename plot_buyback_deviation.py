import matplotlib.pyplot as plt
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from hyperliquid.info import Info
from hyperliquid.utils import constants

def get_hype_price_history():
    print("Fetching HYPE price history from Hyperliquid SDK...")
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    # Fetch last 90 days of data for a better trend view
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=90)
    
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    try:
        candles = info.candles_snapshot(name="HYPE", interval="1d", startTime=start_ms, endTime=end_ms)
        data = []
        for c in candles:
            ts = pd.to_datetime(c['t'], unit='ms', utc=True)
            price = float(c['c'])
            data.append({'date': ts, 'price': price})
            
        df = pd.DataFrame(data)
        if not df.empty:
            df.set_index('date', inplace=True)
        return df
    except Exception as e:
        print(f"Error fetching price: {e}")
        return pd.DataFrame()

def get_protocol_revenue_history():
    print("Fetching Protocol Revenue from DefiLlama...")
    url = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&dataType=dailyRevenue"
    
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = resp.json()
        
        if 'totalDataChart' in data:
            chart_data = data['totalDataChart']
            processed_data = []
            for item in chart_data:
                ts = pd.to_datetime(item[0], unit='s', utc=True)
                revenue = float(item[1])
                processed_data.append({'date': ts, 'revenue': revenue})
            
            df = pd.DataFrame(processed_data)
            df.set_index('date', inplace=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Error fetching revenue: {e}")
        return pd.DataFrame()

def plot_deviation(price_df, revenue_df):
    if price_df.empty or revenue_df.empty:
        print("Missing data for plotting.")
        return

    print("Calculating deviation index...")
    
    # Align data
    combined = pd.merge(price_df, revenue_df, left_index=True, right_index=True, how='inner')
    
    # Calculate Buyback (DefiLlama defines 'Revenue' for Hyperliquid as the 99% portion 
    # of fees that go to the Assistance Fund for buybacks)
    # The user formula: deviation_index = stats['daily_buyback_usd'] / stats['current_price']
    combined['daily_buyback_usd'] = combined['revenue'] 
    combined['deviation_index'] = combined['daily_buyback_usd'] / combined['price']
    
    # Calculate a moving average for the index to smooth out noise
    combined['deviation_index_7d'] = combined['deviation_index'].rolling(window=7).mean()

    # Filter last 60 days for visibility
    cutoff = datetime.now(timezone.utc) - timedelta(days=60)
    df = combined[combined.index >= cutoff]

    if df.empty:
        print("No overlapping data found in the last 60 days.")
        return

    # Plot
    fig, ax1 = plt.subplots(figsize=(14, 7))

    # Axis 1: Deviation Index (Buying Power in Tokens)
    color_index = '#8884d8' # Purple
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Deviation Index (Buyback USD / Price)', color=color_index, fontsize=12, fontweight='bold')
    ax1.fill_between(df.index, df['deviation_index'], color=color_index, alpha=0.2, label='Daily Index')
    ax1.plot(df.index, df['deviation_index_7d'], color=color_index, linewidth=2.5, label='Index (7d SMA)')
    ax1.tick_params(axis='y', labelcolor=color_index)
    ax1.grid(True, linestyle='--', alpha=0.4)

    # Axis 2: HYPE Price
    ax2 = ax1.twinx()
    color_price = '#82ca9d' # Green
    ax2.set_ylabel('HYPE Price (USD)', color=color_price, fontsize=12, fontweight='bold')
    ax2.plot(df.index, df['price'], color=color_price, linewidth=2, linestyle='--', label='HYPE Price')
    ax2.tick_params(axis='y', labelcolor=color_price)

    plt.title('Hyperliquid: Buyback Deviation Index vs $HYPE Price', fontsize=16, pad=20)
    
    # Legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', frameon=True)

    plt.tight_layout()
    
    output_filename = 'hyperliquid_buyback_deviation.png'
    plt.savefig(output_filename, dpi=150)
    print(f"Deviation chart saved to {output_filename}")

if __name__ == "__main__":
    price_df = get_hype_price_history()
    revenue_df = get_protocol_revenue_history()
    
    plot_deviation(price_df, revenue_df)
