import requests

url = "https://api.hyperliquid.xyz/info"
payload = {"type": "metaAndAssetCtxs"}
headers = {"Content-Type": "application/json"}

response = requests.post(url, json=payload, headers=headers)
data = response.json()

meta = data[0]["universe"]
ctxs = data[1]

combined = []
for i in range(len(ctxs)):
    coin_name = meta[i]["name"]
    vol = float(ctxs[i]["dayNtlVlm"])
    oi = float(ctxs[i]["openInterest"])
    combined.append({"coin": coin_name, "volume": vol, "openInterest": oi})

combined.sort(key=lambda x: x["volume"], reverse=True)

total_vol = sum(x["volume"] for x in combined)
total_oi = sum(x["openInterest"] for x in combined)

print(f"Total 24h Volume: ${total_vol:,.2f}")
print(f"Total Open Interest: ${total_oi:,.2f}")
print("\nTop 10 Coins by 24h Volume:")
for i in range(10):
    c = combined[i]
    print(f"{i+1}. {c['coin']}: Vol ${c['volume']:,.2f} | OI {c['openInterest']:,.2f}")

