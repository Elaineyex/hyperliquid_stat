#!/usr/bin/env python3
"""
Generate a source-level Hyperliquid revenue breakdown markdown report.

The daily report uses the prior UTC day as the complete revenue day. This
script mirrors that convention when passed a report date.
"""

import argparse
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
HL_REVENUE_URL = "https://api.llama.fi/overview/fees/hyperliquid"
SPECTRA_REVENUE_URL = "https://api.llama.fi/summary/fees/spectra-v2"
HIP4_PREDICTION_FEE_RATE = float(os.environ.get("HIP4_PREDICTION_FEE_RATE", "0"))


def fetch_json(method, url, **kwargs):
    headers = kwargs.pop("headers", {"User-Agent": "Mozilla/5.0"})
    if method == "post":
        response = requests.post(url, headers=headers, timeout=30, **kwargs)
    else:
        response = requests.get(url, headers=headers, timeout=30, **kwargs)
    response.raise_for_status()
    return response.json()


def fetch_hl_info(payload):
    return fetch_json("post", HL_INFO_URL, json=payload)


def fmt_money(value):
    return f"${value:,.0f}"


def fmt_money_2(value):
    return f"${value:,.2f}"


def fmt_pct(value):
    if value is None or math.isnan(value):
        return "-"
    return f"{value:.2f}%"


def fmt_signed_money(value):
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.0f}"


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def chart_to_map(items):
    rows = {}
    for ts, value in items or []:
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        rows[day] = float(value)
    return rows


def breakdown_to_map(items):
    rows = {}
    for ts, values in items or []:
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        rows[day] = {name: float(amount) for name, amount in values.items()}
    return rows


def get_revenue_data():
    params = {
        "excludeTotalDataChart": "false",
        "excludeTotalDataChartBreakdown": "false",
        "dataType": "dailyRevenue",
    }
    hl_data = fetch_json("get", HL_REVENUE_URL, params=params)
    spectra_data = fetch_json(
        "get",
        SPECTRA_REVENUE_URL,
        params={"dataType": "dailyRevenue"},
    )
    return {
        "gross": chart_to_map(hl_data.get("totalDataChart")),
        "breakdown": breakdown_to_map(hl_data.get("totalDataChartBreakdown")),
        "spectra": chart_to_map(spectra_data.get("totalDataChart")),
    }


def choose_revenue_day(data, report_date):
    preferred = (report_date - timedelta(days=1)).strftime("%Y-%m-%d")
    available = sorted(day for day in data["gross"] if day in data["breakdown"])
    if not available:
        raise ValueError("No DefiLlama revenue breakdown days were returned")
    if preferred in available:
        return preferred
    candidates = [day for day in available if day <= preferred]
    if candidates:
        return candidates[-1]
    return available[-1]


def get_hl_volume_context():
    native_meta, native_ctxs = fetch_hl_info({"type": "metaAndAssetCtxs"})
    native_universe = native_meta.get("universe", [])
    native_volume = sum(float(ctx.get("dayNtlVlm", 0) or 0) for ctx in native_ctxs)
    native_markets = []
    for token, ctx in zip(native_universe, native_ctxs):
        token_volume = float(ctx.get("dayNtlVlm", 0) or 0)
        if token_volume > 0:
            native_markets.append({
                "dex": "native",
                "dex_full": "Native Hyperliquid",
                "market": token.get("name", ""),
                "volume": token_volume,
            })

    spot_meta, spot_ctxs = fetch_hl_info({"type": "spotMetaAndAssetCtxs"})
    spot_universe = spot_meta.get("universe", [])
    spot_volume = sum(float(ctx.get("dayNtlVlm", 0) or 0) for ctx in spot_ctxs)

    dex_rows = []
    perp_dexs = fetch_hl_info({"type": "perpDexs"})
    for idx, dex_info in enumerate(perp_dexs):
        if idx == 0 or not dex_info:
            continue
        dex_name = dex_info.get("name", f"dex{idx}")
        dex_full = dex_info.get("fullName", dex_name)
        meta_ctx = fetch_hl_info({"type": "metaAndAssetCtxs", "dex": dex_name})
        if not meta_ctx or len(meta_ctx) < 2:
            continue
        meta, ctxs = meta_ctx
        universe = meta.get("universe", [])
        volume = sum(float(ctx.get("dayNtlVlm", 0) or 0) for ctx in ctxs)
        top_markets = []
        for token, ctx in zip(universe, ctxs):
            token_volume = float(ctx.get("dayNtlVlm", 0) or 0)
            if token_volume > 0:
                top_markets.append((token.get("name", ""), token_volume))
                native_markets.append({
                    "dex": dex_name,
                    "dex_full": dex_full,
                    "market": token.get("name", ""),
                    "volume": token_volume,
                })
        top_markets = sorted(top_markets, key=lambda item: item[1], reverse=True)[:5]
        dex_rows.append({
            "name": dex_name,
            "full_name": dex_full,
            "volume": volume,
            "markets": len(universe),
            "deployer_fee_scale": dex_info.get("deployerFeeScale"),
            "growth_mode": dex_info.get("isGrowthMode"),
            "top_markets": top_markets,
        })

    return {
        "native_perp_volume": native_volume,
        "native_perp_markets": len(native_universe),
        "spot_volume": spot_volume,
        "spot_markets": len(spot_universe),
        "hip3_dexs": sorted(dex_rows, key=lambda row: row["volume"], reverse=True),
        "perp_markets": sorted(native_markets, key=lambda row: row["volume"], reverse=True),
    }


def classify_source(name):
    if name == "Hyperliquid Perps":
        return "Perps"
    if name == "Hyperliquid Spot Orderbook":
        return "Spot orderbook"
    if "Staking" in name:
        return "HYPE staking"
    return "HyperEVM / ecosystem apps"


def aggregate_categories(breakdown):
    categories = {}
    for source, amount in breakdown.items():
        category = classify_source(source)
        categories[category] = categories.get(category, 0.0) + amount
    return categories


def top_delta_rows(today_breakdown, prev_breakdown):
    names = set(today_breakdown) | set(prev_breakdown)
    rows = []
    for name in names:
        today = today_breakdown.get(name, 0.0)
        prev = prev_breakdown.get(name, 0.0)
        rows.append((name, today, prev, today - prev))
    return sorted(rows, key=lambda row: row[3], reverse=True)


def render_source_table(rows, total):
    lines = [
        "| Source | Revenue | Share |",
        "| :--- | ---: | ---: |",
    ]
    for source, amount in rows:
        lines.append(f"| {source} | {fmt_money(amount)} | {fmt_pct(amount / total * 100 if total else 0)} |")
    return "\n".join(lines)


def render_delta_table(rows, total_delta, limit=12):
    lines = [
        "| Source | Today | Previous Day | Change | Share of Gross Change |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]
    for source, today, prev, delta in rows[:limit]:
        share = delta / total_delta * 100 if total_delta else float("nan")
        lines.append(
            f"| {source} | {fmt_money(today)} | {fmt_money(prev)} | "
            f"{fmt_signed_money(delta)} | {fmt_pct(share)} |"
        )
    return "\n".join(lines)


def render_volume_table(volume_context):
    native = volume_context["native_perp_volume"]
    hip3 = sum(row["volume"] for row in volume_context["hip3_dexs"])
    total = native + hip3
    lines = [
        "| Bucket | Live 24h Notional Volume | Share | Markets |",
        "| :--- | ---: | ---: | ---: |",
        f"| Native Hyperliquid perps | {fmt_money(native)} | {fmt_pct(native / total * 100 if total else 0)} | {volume_context['native_perp_markets']} |",
        f"| HIP-3 / builder perps | {fmt_money(hip3)} | {fmt_pct(hip3 / total * 100 if total else 0)} | {sum(row['markets'] for row in volume_context['hip3_dexs'])} |",
        f"| **Total perps** | **{fmt_money(total)}** | **100.00%** | **{volume_context['native_perp_markets'] + sum(row['markets'] for row in volume_context['hip3_dexs'])}** |",
    ]
    return "\n".join(lines)


def render_hip3_table(volume_context):
    lines = [
        "| DEX | Full Name | Markets | Live 24h Notional Volume | Share of HIP-3 Volume | Deployer Fee Scale | Growth Mode |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    total = sum(row["volume"] for row in volume_context["hip3_dexs"])
    for row in volume_context["hip3_dexs"]:
        scale = row["deployer_fee_scale"]
        scale_display = "-" if scale is None else f"{float(scale):.4f}"
        growth = "yes" if row["growth_mode"] else "no"
        lines.append(
            f"| `{row['name']}` | {row['full_name']} | {row['markets']} | {fmt_money(row['volume'])} | "
            f"{fmt_pct(row['volume'] / total * 100 if total else 0)} | {scale_display} | {growth} |"
        )
    return "\n".join(lines)


def render_top_perp_markets(volume_context, limit=25):
    lines = [
        "| Rank | Market | Venue | Live 24h Notional Volume | Share of Total Perp Volume |",
        "| ---: | :--- | :--- | ---: | ---: |",
    ]
    total = sum(row["volume"] for row in volume_context["perp_markets"])
    for idx, row in enumerate(volume_context["perp_markets"][:limit], start=1):
        venue = "Native" if row["dex"] == "native" else f"HIP-3 `{row['dex']}`"
        lines.append(
            f"| {idx} | `{row['market']}` | {venue} | {fmt_money(row['volume'])} | "
            f"{fmt_pct(row['volume'] / total * 100 if total else 0)} |"
        )
    return "\n".join(lines)


def render_native_top_markets(volume_context, limit=15):
    native_rows = [row for row in volume_context["perp_markets"] if row["dex"] == "native"]
    total = sum(row["volume"] for row in native_rows)
    lines = [
        "| Rank | Native Market | Live 24h Notional Volume | Share of Native Perp Volume |",
        "| ---: | :--- | ---: | ---: |",
    ]
    for idx, row in enumerate(native_rows[:limit], start=1):
        lines.append(
            f"| {idx} | `{row['market']}` | {fmt_money(row['volume'])} | "
            f"{fmt_pct(row['volume'] / total * 100 if total else 0)} |"
        )
    return "\n".join(lines)


def render_top_markets(volume_context):
    lines = [
        "| DEX | Top Live Markets by 24h Notional Volume |",
        "| :--- | :--- |",
    ]
    for row in volume_context["hip3_dexs"]:
        markets = ", ".join(f"`{name}` {fmt_money(volume)}" for name, volume in row["top_markets"])
        lines.append(f"| `{row['name']}` | {markets or '-'} |")
    return "\n".join(lines)


def build_report(report_date, output_dir):
    revenue_data = get_revenue_data()
    revenue_day = choose_revenue_day(revenue_data, report_date)
    prev_day = (parse_date(revenue_day) - timedelta(days=1)).strftime("%Y-%m-%d")
    if prev_day not in revenue_data["breakdown"]:
        raise ValueError(f"Missing previous-day breakdown for {prev_day}")

    today_breakdown = revenue_data["breakdown"][revenue_day]
    prev_breakdown = revenue_data["breakdown"][prev_day]
    gross = revenue_data["gross"].get(revenue_day, sum(today_breakdown.values()))
    prev_gross = revenue_data["gross"].get(prev_day, sum(prev_breakdown.values()))
    gross_delta = gross - prev_gross
    spectra = revenue_data["spectra"].get(revenue_day, 0.0)
    net = max(0.0, gross - spectra)
    volume_context = get_hl_volume_context()

    categories = aggregate_categories(today_breakdown)
    prev_categories = aggregate_categories(prev_breakdown)
    category_rows = top_delta_rows(categories, prev_categories)
    source_rows = sorted(today_breakdown.items(), key=lambda item: item[1], reverse=True)
    delta_rows = top_delta_rows(today_breakdown, prev_breakdown)

    perps = today_breakdown.get("Hyperliquid Perps", 0.0)
    spot = today_breakdown.get("Hyperliquid Spot Orderbook", 0.0)
    ecosystem = gross - perps - spot
    native_volume = volume_context["native_perp_volume"]
    hip3_volume = sum(row["volume"] for row in volume_context["hip3_dexs"])

    report = f"""# Hyperliquid Revenue Contributor Tracker - {revenue_day}

Source snapshot for the complete revenue day used by the {report_date.strftime('%Y-%m-%d')} daily report.

## Summary

| Metric | Value |
| :--- | ---: |
| DefiLlama Hyperliquid gross revenue | {fmt_money(gross)} |
| Previous day gross revenue | {fmt_money(prev_gross)} |
| Day-over-day change | {fmt_signed_money(gross_delta)} |
| Spectra V2 adjustment | -{fmt_money_2(spectra)} |
| Net protocol revenue used in report | {fmt_money(net)} |
| HIP-4 prediction-market fee rate configured | {HIP4_PREDICTION_FEE_RATE:.4%} |

## What Drove The Move

| Category | Today | Previous Day | Change | Share of Gross Change |
| :--- | ---: | ---: | ---: | ---: |
"""
    for category, today, prev, delta in category_rows:
        share = delta / gross_delta * 100 if gross_delta else float("nan")
        report += f"| {category} | {fmt_money(today)} | {fmt_money(prev)} | {fmt_signed_money(delta)} | {fmt_pct(share)} |\n"

    report += f"""
## Main Revenue Sources

| Source | Revenue | Share of Gross |
| :--- | ---: | ---: |
| Hyperliquid Perps | {fmt_money(perps)} | {fmt_pct(perps / gross * 100 if gross else 0)} |
| Hyperliquid Spot Orderbook | {fmt_money(spot)} | {fmt_pct(spot / gross * 100 if gross else 0)} |
| HyperEVM / ecosystem apps and staking | {fmt_money(ecosystem)} | {fmt_pct(ecosystem / gross * 100 if gross else 0)} |
| **Gross total** | **{fmt_money(gross)}** | **100.00%** |
| Spectra V2 adjustment | -{fmt_money_2(spectra)} | - |
| **Net report total** | **{fmt_money(net)}** | - |

## Day-Over-Day Source Drivers

{render_delta_table(delta_rows, gross_delta)}

## Live Perp Volume Context

DefiLlama's `Hyperliquid Perps` revenue bucket is blended. Hyperliquid's API exposes current native and HIP-3 / builder-deployed perp notional volume, which helps explain where the perps revenue pressure is coming from. This is live 24h volume context, not an exact historical revenue split for {revenue_day}.

{render_volume_table(volume_context)}

## Top Perp Markets By Notional

{render_top_perp_markets(volume_context)}

## Top Native Hyperliquid Perp Markets

{render_native_top_markets(volume_context)}

## HIP-3 Builder Perp Context

{render_hip3_table(volume_context)}

## Top HIP-3 Markets

{render_top_markets(volume_context)}

## Detailed Source Table

{render_source_table(source_rows, gross)}

## Interpretation

- Perps remain the dominant revenue contributor when `Hyperliquid Perps` is the largest DefiLlama source bucket.
- Spot orderbook revenue is separately visible and should not be mixed into the perp fee model.
- Ecosystem and staking rows are app-level or staking-related DefiLlama sources around Hyperliquid; they are useful for ecosystem activity, but they are not native perp trading fees.
- HIP-3 perps should be tracked separately from native perps because builder-deployed venues can add deployer fee economics on top of the base HyperCore fee system.

## Data Sources

- DefiLlama fees overview: `https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false&dataType=dailyRevenue`
- DefiLlama Spectra V2 fees summary: `https://api.llama.fi/summary/fees/spectra-v2?dataType=dailyRevenue`
- Hyperliquid info endpoint: `https://api.hyperliquid.xyz/info`
- Hyperliquid fields used: `perpDexs`, `metaAndAssetCtxs`, and `spotMetaAndAssetCtxs`
"""

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{revenue_day}-revenue-breakdown.md"
    output_path.write_text(report, encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate Hyperliquid revenue contributor markdown.")
    parser.add_argument(
        "report_date",
        nargs="?",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="Daily report date in YYYY-MM-DD format. Revenue day is the prior UTC day.",
    )
    parser.add_argument("--output-dir", default=str(SCRIPT_DIR / "logs"))
    args = parser.parse_args()

    output_path = build_report(parse_date(args.report_date), Path(args.output_dir))
    print(f"Revenue breakdown generated: {output_path}")


if __name__ == "__main__":
    main()
