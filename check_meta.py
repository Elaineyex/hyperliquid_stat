import requests
import json

response = requests.get("https://app.hyperliquid.xyz/api/explore")
if response.status_code == 200:
    try:
        data = response.json()
        print(json.dumps(data)[:1000])
    except Exception as e:
        print("Not json", e, response.text[:200])

response2 = requests.post("https://api.hyperliquid.xyz/info", json={"type": "meta"})
data2 = response2.json()
print("Perp universe keys:", data2['universe'][0].keys() if data2.get('universe') else None)

response3 = requests.post("https://api.hyperliquid.xyz/info", json={"type": "spotMeta"})
data3 = response3.json()
print("Spot universe keys:", data3['universe'][0].keys() if data3.get('universe') else None)
