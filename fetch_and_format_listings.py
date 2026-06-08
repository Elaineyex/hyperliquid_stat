import requests
import json
import csv

url = "https://api.hyperliquid.xyz/info"

# Explicit TradFi categories 
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

# Ticker to Human Readable Name Mapping
MAPPING = {
    "AAPL": "Apple",
    "ALUMINIUM": "Aluminium",
    "AMD": "Advanced Micro Devices",
    "AMZN": "Amazon",
    "ANTHROPIC": "Anthropic (Pre-IPO)",
    "BABA": "Alibaba",
    "BIOTECH": "Biotech Index",
    "BMNR": "Bitcoin Miners Index",
    "BRENTOIL": "Brent Crude Oil",
    "BRENT": "Brent Crude Oil",
    "CL": "Crude Oil",
    "COIN": "Coinbase",
    "COPPER": "Copper",
    "COST": "Costco",
    "CRCL": "Circle (Pre-IPO)",
    "CRWV": "CoreWeave (Pre-IPO)",
    "DEFENSE": "Defense Sector Index",
    "DXY": "US Dollar Index",
    "ENERGY": "Energy Sector Index",
    "EUR": "Euro",
    "EWJ": "iShares MSCI Japan ETF",
    "EWY": "iShares MSCI South Korea ETF",
    "GAS": "Natural Gas",
    "GLDMINE": "Gold Miners Index",
    "GME": "GameStop",
    "GOLD": "Gold",
    "GOLDJM": "Gold",
    "GOOGL": "Alphabet (Google)",
    "HIMS": "Hims & Hers Health",
    "HOOD": "Robinhood",
    "HYUNDAI": "Hyundai",
    "INFOTECH": "Information Technology Index",
    "INTC": "Intel",
    "JP225": "Nikkei 225",
    "JPN225": "Nikkei 225",
    "JPY": "Japanese Yen",
    "KIOXIA": "Kioxia",
    "KR200": "KOSPI 200",
    "KWEB": "KraneShares CSI China Internet ETF",
    "LLY": "Eli Lilly",
    "MAG7": "Magnificent 7 Index",
    "META": "Meta Platforms",
    "MSFT": "Microsoft",
    "MSTR": "MicroStrategy",
    "MU": "Micron Technology",
    "NATGAS": "Natural Gas",
    "NFLX": "Netflix",
    "NUCLEAR": "Nuclear Sector Index",
    "NVDA": "Nvidia",
    "OIL": "Oil",
    "OPENAI": "OpenAI (Pre-IPO)",
    "ORCL": "Oracle",
    "PALLADIUM": "Palladium",
    "PLATINUM": "Platinum",
    "PLTR": "Palantir",
    "RIVN": "Rivian",
    "ROBOT": "Robotics Index",
    "RTX": "RTX Corporation",
    "SEMI": "Semiconductors Index",
    "SEMIS": "Semiconductors Index",
    "SILVER": "Silver",
    "SILVERJM": "Silver",
    "SKHX": "SK Hynix",
    "SMALL2000": "Russell 2000",
    "SMSN": "Samsung",
    "SNDK": "SanDisk",
    "SOFTBANK": "SoftBank",
    "SP500": "S&P 500",
    "SPACEX": "SpaceX (Pre-IPO)",
    "TENCENT": "Tencent",
    "TSLA": "Tesla",
    "TSM": "Taiwan Semiconductor",
    "URANIUM": "Uranium",
    "URNM": "Sprott Uranium Miners ETF",
    "US100": "Nasdaq 100",
    "US500": "S&P 500",
    "USA100": "Nasdaq 100",
    "USA500": "S&P 500",
    "USAR": "USAR",
    "USBOND": "US Treasury Bond",
    "USDE": "Ethena USDe",
    "USENERGY": "US Energy Index",
    "USOIL": "US Oil",
    "USTECH": "US Tech Index (Nasdaq)",
    "VIX": "CBOE Volatility Index",
    "WTI": "WTI Crude Oil",
    "XIAOMI": "Xiaomi",
    "XYZ100": "Nasdaq 100",
}

def get_crypto_name(ticker):
    cryptos = {
        "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "DOGE": "Dogecoin",
        "ADA": "Cardano", "BCH": "Bitcoin Cash", "BNB": "Binance Coin", "ENA": "Ethena",
        "LINK": "Chainlink", "LTC": "Litecoin", "SUI": "Sui", "XMR": "Monero",
        "XRP": "XRP", "ZEC": "Zcash", "HYPE": "Hyperliquid", "IP": "Story Protocol",
        "FARTCOIN": "Fartcoin", "PUMP": "Pump.fun", "LIGHTER": "Lighter", "XPL": "XPL", "LIT": "Litentry"
    }
    return cryptos.get(ticker, ticker)

def fetch_data(t, **kwargs):
    try:
        resp = requests.post(url, json={"type": t, **kwargs})
        return resp.json()
    except Exception as e:
        print(f"Error fetching {t}: {e}")
        return None

def main():
    print("Fetching DEX info...")
    perp_dexs = fetch_data("perpDexs")
    annotations_resp = fetch_data("perpConciseAnnotations") or []

    annotations = {}
    for item in annotations_resp:
        if len(item) == 2:
            ticker, data = item
            annotations[ticker] = data.get("category", "")

    results = []

    print("Analyzing TradFi and HIP-3 listings...")

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
        
        # Fetch asset contexts for specific DEX
        meta_ctx = fetch_data("metaAndAssetCtxs", dex=dex_name)
        if not meta_ctx or len(meta_ctx) < 2:
            continue
            
        universe = meta_ctx[0].get("universe", [])
        ctxs = meta_ctx[1]
        
        for i, token in enumerate(universe):
            ticker = token["name"]
            base_ticker = ticker.split(":")[-1]
            ctx = ctxs[i] if i < len(ctxs) else {}
            
            # Map human readable name
            name = MAPPING.get(base_ticker)
            if not name:
                name = get_crypto_name(base_ticker)

            api_category = annotations.get(ticker, "")
            
            if ticker in TRADFI_MAP:
                category = "TradFi"
                cat_suffix = TRADFI_MAP[ticker]
                explanation = f"{name} ({cat_suffix})"
            else:
                category = "HIP-3"
                cat_suffix = f" ({api_category.capitalize()})" if api_category else ""
                explanation = f"{name} - HIP-3 Perp on {dex_full} ({dex_name}){cat_suffix}"
                
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

    output_filename = "tradfi_hip3_listings.csv"
    with open(output_filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "category", "explanation", "last_price", "24h_change_pct", "8h_funding_pct", "volume", "open_interest", "dex", "issue_reason"])
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(f"\nSaved {len(results)} listings to {output_filename}")

if __name__ == "__main__":
    main()