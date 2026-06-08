import requests
import datetime

print("Fetching Historical Daily Volume from DefiLlama...")
url = "https://api.llama.fi/overview/dexs/hyperliquid?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true&dataType=dailyVolume"

response = requests.get(url)
if response.status_code == 200:
    data = response.json()
    chart = data.get("totalDataChart", [])
    
    print("\nLast 7 Days Volume vs Revenue Estimate:")
    print("Date        | Volume          |")
    print("-" * 35)
    
    # Get last 7 days
    recent = chart[-8:]
    for item in recent:
        ts = int(item[0])
        vol = float(item[1])
        date_str = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime('%Y-%m-%d')
        print(f"{date_str}  | ${vol:13,.2f} |")
else:
    print(f"Failed to fetch: {response.status_code}")
