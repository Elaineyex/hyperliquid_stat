import requests
import json
import pandas as pd

def print_breakdown():
    print("Fetching Hyperliquid Revenue Breakdown from DefiLlama...")
    url = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false&dataType=dailyRevenue"
    
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = resp.json()
        
        if 'totalDataChartBreakdown' in data:
            breakdown_list = data['totalDataChartBreakdown']
            if not breakdown_list:
                print("Breakdown list is empty.")
                return
                
            sample_day = breakdown_list[-1]
            timestamp = sample_day[0]
            date_str = pd.to_datetime(timestamp, unit='s', utc=True).strftime('%Y-%m-%d')
            categories = sample_day[1]
            
            print(f"\nBreakdown for Date: {date_str} (TS: {timestamp})")
            print("-" * 40)
            
            sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
            
            for cat, val in sorted_cats:
                print(f"{cat:.<30} ${val:,.2f}")
                
            total = sum(categories.values())
            print("-" * 40)
            print(f"{'TOTAL':<30} ${total:,.2f}")
            
        else:
            print("Key 'totalDataChartBreakdown' not found in response.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print_breakdown()