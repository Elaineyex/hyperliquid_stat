import requests
import json

def fetch_data(type_str):
    url = "https://api.hyperliquid.xyz/info"
    resp = requests.post(url, json={"type": type_str})
    return resp.json()

perps = fetch_data("metaAndAssetCtxs")
spots = fetch_data("spotMetaAndAssetCtxs")

perp_universe = perps[0]["universe"]
perp_ctxs = perps[1]

spot_universe = spots[0]["universe"]
spot_tokens = spots[0]["tokens"]
spot_ctxs = spots[1]

print("Total perps:", len(perp_universe))
print("Total spots:", len(spot_universe))
print("Total spot tokens:", len(spot_tokens))

# Let's save the meta out so we can inspect it easily
with open("meta_debug.json", "w") as f:
    json.dump({
        "perp_universe": perp_universe,
        "perp_ctxs_sample": perp_ctxs[:2] if perp_ctxs else [],
        "spot_universe": spot_universe,
        "spot_tokens": spot_tokens,
        "spot_ctxs_sample": spot_ctxs[:2] if spot_ctxs else []
    }, f, indent=2)

print("Saved meta_debug.json for inspection.")
