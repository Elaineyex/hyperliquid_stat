import requests
import json

url = "https://api.hyperliquid.xyz/info"

def get_data(t, **kwargs):
    resp = requests.post(url, json={"type": t, **kwargs})
    try:
        return resp.json()
    except:
        return None

all_perp_metas = get_data("allPerpMetas")
perp_dexs = get_data("perpDexs")

print("DEXs:", perp_dexs)

tradfi_universe = []
hip3_universe = []

for idx, meta in enumerate(all_perp_metas):
    if not meta:
        continue
    dex_name = perp_dexs[idx] if idx < len(perp_dexs) else f"Dex-{idx}"
    universe = meta.get("universe", [])
    print(f"DEX {idx} ({dex_name}): {len(universe)} pairs")
    if dex_name == "xyz":
        print("xyz pairs:", [u['name'] for u in universe][:5])
    if dex_name and dex_name.lower() not in ["none", "hyperliquid"]:
        print(f"Other DEX pairs ({dex_name}):", [u['name'] for u in universe][:5])

# Let's save the metas for deep analysis
with open("all_perp_metas.json", "w") as f:
    json.dump({
        "dexs": perp_dexs,
        "metas": all_perp_metas
    }, f, indent=2)
