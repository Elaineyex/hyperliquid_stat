import requests
import json
import pandas as pd

def print_breakdown():
    url = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false&dataType=dailyRevenue"
    resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = resp.json()
    breakdown_list = data['totalDataChartBreakdown']
    for sample_day in breakdown_list[-5:]:
        timestamp = sample_day[0]
        date_str = pd.to_datetime(timestamp, unit='s', utc=True).strftime('%Y-%m-%d')
        categories = sample_day[1]
        print(f"Date: {date_str} - Total: {sum(categories.values()):,.2f}")
print_breakdown()
