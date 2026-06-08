import requests
import json
import csv

url = "https://api.hyperliquid.xyz/info"

TRADFI_MAP = {
    "xyz:BRENT": "Commodities", "xyz:CL": "Commodities", "xyz:COPPER": "Commodities", 
    "xyz:GOLD": "Commodities", "xyz:NATGAS": "Commodities", "xyz:PLATINUM": "Commodities", 
    "xyz:SILVER": "Commodities", "xyz:URNM": "Commodities", 
    "flx:COPPER": "Commodities", "flx:GOLD": "Commodities", "flx:OIL": "Commodities", 
    "flx:PALLADIUM": "Commodities", "flx:PLATINUM": "Commodities", "flx:SILVER": "Commodities", 
    "km:GOLD": "Commodities", "km:SILVER": "Commodities", "km:USOIL": "Commodities",
    "xyz:JPY": "Forex", "xyz:EUR": "Forex",
    "vntl:ANTHROPIC": "Pre-IPO", "vntl:OPENAI": "Pre-IPO", "vntl:SPACEX": "Pre-IPO",
    "km:US500": "Indices", "km:USTECH": "Indices", "xyz:XYZ100": "Indices",
    "vntl:BIOTECH": "Indices", "vntl:DEFENSE": "Indices", "vntl:ENERGY": "Indices",
    "vntl:INFOTECH": "Indices", "vntl:MAG7": "Indices", "vntl:NUCLEAR": "Indices",
    "vntl:ROBOT": "Indices", "vntl:SEMIS": "Indices"
}

def fetch_data(t, **kwargs):
    try:
        resp = requests.post(url, json={"type": t, **kwargs})
        return resp.json()
    except Exception as e:
        print(f"Error fetching {t}: {e}")
        return None

perp_dexs = fetch_data("perpDexs")
all_perp_metas = fetch_data("allPerpMetas")
annotations_resp = fetch_data("perpConciseAnnotations") or []

annotations = {}
for item in annotations_resp:
    if len(item) == 2:
        ticker, data = item
        annotations[ticker] = data.get("category", "")

results = []

print("Analyzing TradFi and HIP-3 listings...")

# Let's map maxLeverage or marginTable to see if trading is disabled.
# Also, OI cap from perpDexs
oi_caps = {}
for dex in perp_dexs:
    if not dex: continue
    for asset, cap in dex.get("assetToStreamingOiCap", []):
        oi_caps[asset] = float(cap)

for idx, dex_info in enumerate(perp_dexs):
    if idx == 0 or dex_info is None:
        continue # Skip native Hyperliquid perps
    
    dex_name = dex_info.get("name", f"dex{idx}")
    dex_full = dex_info.get("fullName", dex_name)
    
    # Fetch asset contexts
    meta_ctx = fetch_data("metaAndAssetCtxs", dex=dex_name)
    if not meta_ctx or len(meta_ctx) < 2:
        continue
        
    universe = meta_ctx[0].get("universe", [])
    ctxs = meta_ctx[1]
    
    for i, token in enumerate(universe):
        ticker = token["name"]
        ctx = ctxs[i] if i < len(ctxs) else {}
        
        # Category and explanation
        category = ""
        explanation = ""
        
        api_category = annotations.get(ticker, "")
        
        if ticker in TRADFI_MAP:
            category = "TradFi"
            explanation = f"TradFi - {TRADFI_MAP[ticker]}"
        else:
            category = "HIP-3"
            cat_suffix = f" - {api_category.capitalize()}" if api_category else ""
            explanation = f"HIP-3 Perp on {dex_full} ({dex_name}){cat_suffix}"
            
        last_price = float(ctx.get("markPx", 0))
        prev_price = float(ctx.get("prevDayPx", 0))
        
        if prev_price > 0:
            pct_change_24h = (last_price - prev_price) / prev_price * 100
        else:
            pct_change_24h = 0.0
            
        funding_1h = float(ctx.get("funding", 0))
        funding_8h_pct = funding_1h * 8 * 100
        
        volume = float(ctx.get("dayNtlVlm", 0))
        oi = float(ctx.get("openInterest", 0))
        
        cap = oi_caps.get(ticker, -1)
        
        issue_reason = ""
        if volume == 0 or last_price == 0:
            if cap == 0:
                issue_reason = "Open Interest cap is 0 (Trading disabled or pending launch)"
            elif token.get("maxLeverage", 0) <= 0:
                issue_reason = "Max leverage is 0 (Trading halted)"
            elif last_price == 0:
                issue_reason = "No oracle price updates"
            else:
                issue_reason = "No active liquidity or market making for this pair"
                
        results.append({
            "ticker": ticker,
            "category": category,
            "explanation": explanation,
            "last_price": last_price,
            "24h_change_pct": pct_change_24h,
            "8h_funding_pct": funding_8h_pct,
            "volume": volume,
            "open_interest": oi,
            "dex": dex_name,
            "issue_reason": issue_reason
        })

# Save to CSV
with open("tradfi_hip3_listings.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["ticker", "category", "explanation", "last_price", "24h_change_pct", "8h_funding_pct", "volume", "open_interest", "dex", "issue_reason"])
    writer.writeheader()
    for row in results:
        writer.writerow(row)

print("\n--- Zero Volume / No Price Analysis ---")
zero_vol_tokens = [r for r in results if r["volume"] == 0 or r["last_price"] == 0]
print(f"Found {len(zero_vol_tokens)} listings with issues.")
for z in zero_vol_tokens:
    print(f"- {z['ticker']} ({z['explanation']}): Price=${z['last_price']}, Vol={z['volume']}, Reason: {z['issue_reason']}")

print(f"\nSaved {len(results)} listings to tradfi_hip3_listings.csv")
