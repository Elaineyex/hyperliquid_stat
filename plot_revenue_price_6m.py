import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from hyperliquid.info import Info
from hyperliquid.utils import constants

def get_hype_price_history():
    print("Fetching $HYPE price history from Hyperliquid SDK...")
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    # Request 190 days to ensure we have a full 6 months
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=190)
    
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    try:
        # Fetch HYPE daily candles
        candles = info.candles_snapshot(name="HYPE", interval="1d", startTime=start_ms, endTime=end_ms)
        data = []
        for c in candles:
            data.append({
                'date': pd.to_datetime(c['t'], unit='ms', utc=True),
                'price': float(c['c'])
            })
        df = pd.DataFrame(data).set_index('date')
        return df
    except Exception as e:
        print(f"Failed to fetch price: {e}")
        return None

def get_protocol_revenue_history():
    print("Fetching Protocol Revenue from DefiLlama...")
    url = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&dataType=dailyRevenue"
    
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = resp.json()
        if 'totalDataChart' in data:
            chart_data = data['totalDataChart']
            processed = []
            for item in chart_data:
                processed.append({
                    'date': pd.to_datetime(item[0], unit='s', utc=True),
                    'revenue': float(item[1])
                })
            df = pd.DataFrame(processed).set_index('date')
            return df
        return None
    except Exception as e:
        print(f"Failed to fetch revenue: {e}")
        return None

def plot_data(price_df, revenue_df):
    print("Generating 6-month trend plot...")
    
    # Merge and align data
    combined = pd.merge(price_df, revenue_df, left_index=True, right_index=True, how='inner')
    
    # Filter for last 180 days (approx 6 months)
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    combined = combined[combined.index >= cutoff]
    
    if combined.empty:
        print("No overlapping data found for the last 6 months.")
        # Fallback to show whatever overlap we have if 6m is too long
        combined = pd.merge(price_df, revenue_df, left_index=True, right_index=True, how='inner')
        if combined.empty:
            return
        print(f"Plotting available overlap: {combined.index.min()} to {combined.index.max()}")

    # Create Plot
    fig, ax1 = plt.subplots(figsize=(14, 7))

    # Left Axis: Protocol Revenue
    color_rev = '#1f77b4' # Blue
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Daily Revenue (USD)', color=color_rev, fontsize=12)
    
    # Raw data as light line
    ax1.plot(combined.index, combined['revenue'], color=color_rev, alpha=0.3, label='Daily Revenue (Raw)')
    # 7-day Moving Average for trend
    ax1.plot(combined.index, combined['revenue'].rolling(window=7).mean(), color=color_rev, linewidth=2, label='Revenue (7d Avg)')
    
    ax1.tick_params(axis='y', labelcolor=color_rev)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
    ax1.grid(True, which='both', linestyle='--', alpha=0.4)

    # Right Axis: HYPE Price
    ax2 = ax1.twinx()
    color_price = '#2ca02c' # Green
    ax2.set_ylabel('$HYPE Price (USD)', color=color_price, fontsize=12)
    ax2.plot(combined.index, combined['price'], color=color_price, linewidth=2.5, label='HYPE Price')
    ax2.tick_params(axis='y', labelcolor=color_price)

    # --- X-axis optimization: Interval by 1 Month ---
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=0)

    # Title and Legend
    plt.title('Hyperliquid: 6-Month Protocol Revenue vs $HYPE Price', fontsize=14, pad=20)
    
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    fig.tight_layout()
    
    output_name = 'hyperliquid_6m_trend.png'
    plt.savefig(output_name, dpi=150)
    print(f"Chart saved as: {output_name}")

if __name__ == "__main__":
    p_df = get_hype_price_history()
    r_df = get_protocol_revenue_history()
    
    if p_df is not None and r_df is not None:
        plot_data(p_df, r_df)
    else:
        print("Data retrieval incomplete.")
