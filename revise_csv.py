import csv

mapping = {
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

rows = []
with open("tradfi_hip3_listings.csv", "r") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        ticker = row["ticker"]
        base_ticker = ticker.split(":")[-1]
        
        name = mapping.get(base_ticker)
        if not name:
            name = get_crypto_name(base_ticker)
            
        original_exp = row["explanation"]
        
        if "TradFi" in original_exp:
            cat = original_exp.split("-")[-1].strip()
            row["explanation"] = f"{name} ({cat})"
        else:
            parts = original_exp.split(" - ")
            base_exp = parts[0]
            if len(parts) > 1:
                row["explanation"] = f"{name} - {base_exp} ({parts[1]})"
            else:
                row["explanation"] = f"{name} - {base_exp}"
                
        rows.append(row)

with open("tradfi_hip3_listings.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

print("Revised CSV with company/asset names.")
