from hyperliquid.info import Info
from hyperliquid.utils import constants
import requests
import json

def discover():
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    # 1. Check symbols
    print("Fetching meta...")
    meta = info.meta()
    universe = meta['universe']
    hype_found = False
    for asset in universe:
        if asset['name'] == 'HYPE':
            print("Found symbol: HYPE")
            hype_found = True
            break
    
    if not hype_found:
        print("Symbol 'HYPE' not found in universe. Listing first 5:")
        for i in range(min(5, len(universe))):
            print(universe[i]['name'])

    # 2. Check stats endpoint for revenue
    url = constants.MAINNET_API_URL + "/info"
    print(f"Checking stats at {url}...")
    
    # Try globalStats
    try:
        resp = requests.post(url, json={"type": "globalStats"})
        if resp.status_code == 200:
            print("globalStats keys:", resp.json().keys())
    except Exception as e:
        print("globalStats failed:", e)

    # Try to find historical stats or similar?
    # Common endpoints for other DEXs might be /stats/history
    
if __name__ == "__main__":
    discover()
