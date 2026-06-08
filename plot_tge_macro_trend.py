import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import requests
from hyperliquid.info import Info
from hyperliquid.utils import constants


SCRIPT_DIR = Path(__file__).resolve().parent
HL_INFO_URL = "https://api.hyperliquid.xyz/info"
HIP4_PREDICTION_FEE_RATE = float(os.environ.get("HIP4_PREDICTION_FEE_RATE", "0"))

START_DATE = pd.Timestamp("2024-11-29", tz="UTC")
TARGET_DATE = pd.Timestamp(datetime.now(timezone.utc)).normalize()
OUTPUT_PATH = SCRIPT_DIR / "hyperliquid_tge_macro_trend.png"

TOTAL_HYPE_SUPPLY = 1_000_000_000
GENESIS_DISTRIBUTION = 310_000_000
FUTURE_COMMUNITY_REWARDS = 389_000_000
HYPER_FOUNDATION_BUDGET = 60_100_000
CORE_CONTRIBUTORS = 238_000_000
COMMUNITY_GRANTS = 3_000_000

SIXTY_MONTH_VEST_END = pd.Timestamp("2029-11-29", tz="UTC")
TWELVE_MONTH_CLIFF = pd.Timestamp("2025-11-29", tz="UTC")
THIRTY_SIX_MONTH_VEST_END = pd.Timestamp("2028-11-29", tz="UTC")


def fetch_hl_info(payload):
    response = requests.post(HL_INFO_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def get_sdk_price_history(symbol, candle_symbol=None):
    candle_symbol = candle_symbol or symbol
    print(f"Fetching {symbol} price history from Hyperliquid SDK ({candle_symbol})...")
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    candles = info.candles_snapshot(
        name=candle_symbol,
        interval="1d",
        startTime=int(START_DATE.timestamp() * 1000),
        endTime=int((TARGET_DATE + pd.Timedelta(days=1)).timestamp() * 1000),
    )

    rows = [
        {
            "date": pd.to_datetime(candle["t"], unit="ms", utc=True).normalize(),
            f"{symbol}_price": float(candle["c"]),
        }
        for candle in candles
    ]
    if not rows:
        return pd.DataFrame(columns=[f"{symbol}_price"])
    return pd.DataFrame(rows).drop_duplicates("date").set_index("date").sort_index()


def get_hip4_prediction_market_revenue_history():
    print("Fetching HIP-4 Prediction Market Revenue from Hyperliquid...")
    try:
        outcome_meta = fetch_hl_info({"type": "outcomeMeta"})
        outcomes = outcome_meta.get("outcomes", [])
        if not outcomes:
            print("  No active HIP-4 outcome markets found.")
            return pd.DataFrame(columns=["hip4_prediction_volume", "hip4_prediction_revenue"])

        start_ms = int(START_DATE.timestamp() * 1000)
        end_ms = int((TARGET_DATE + pd.Timedelta(days=1)).timestamp() * 1000)
        daily_totals = {}
        outcome_coins = []

        for outcome in outcomes:
            outcome_id = int(outcome["outcome"])
            side_specs = outcome.get("sideSpecs", [])
            for side in range(len(side_specs)):
                coin = f"#{outcome_id * 10 + side}"
                outcome_coins.append(coin)
                candles = fetch_hl_info(
                    {
                        "type": "candleSnapshot",
                        "req": {
                            "coin": coin,
                            "interval": "1d",
                            "startTime": start_ms,
                            "endTime": end_ms,
                        },
                    }
                )
                for candle in candles:
                    dt = pd.to_datetime(candle["t"], unit="ms", utc=True).normalize()
                    volume = float(candle.get("v", 0) or 0)
                    daily_totals[dt] = daily_totals.get(dt, 0.0) + volume

        rows = [
            {
                "date": dt,
                "hip4_prediction_volume": volume,
                "hip4_prediction_revenue": volume * HIP4_PREDICTION_FEE_RATE,
            }
            for dt, volume in daily_totals.items()
        ]
        print(
            f"  Found {len(outcomes)} active outcome market(s), {len(outcome_coins)} side coin(s); "
            f"HIP-4 fee rate {HIP4_PREDICTION_FEE_RATE:.4%}"
        )
        if not rows:
            return pd.DataFrame(columns=["hip4_prediction_volume", "hip4_prediction_revenue"])
        return pd.DataFrame(rows).set_index("date").sort_index()
    except Exception as exc:
        print(f"Failed to fetch HIP-4 prediction market revenue: {exc}")
        return pd.DataFrame(columns=["hip4_prediction_volume", "hip4_prediction_revenue"])


def get_protocol_revenue_history():
    print("Fetching Protocol Revenue from DefiLlama (excluding Spectra V2)...")
    url_hl = "https://api.llama.fi/overview/fees/hyperliquid?excludeTotalDataChart=false&dataType=dailyRevenue"
    url_spectra = "https://api.llama.fi/summary/fees/spectra-v2?dataType=dailyRevenue"

    resp_hl = requests.get(url_hl, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp_hl.raise_for_status()
    data_hl = resp_hl.json()

    resp_spectra = requests.get(url_spectra, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp_spectra.raise_for_status()
    data_spectra = resp_spectra.json()

    hl_chart = {
        pd.to_datetime(item[0], unit="s", utc=True).normalize(): float(item[1])
        for item in data_hl.get("totalDataChart", [])
    }
    spectra_chart = {
        pd.to_datetime(item[0], unit="s", utc=True).normalize(): float(item[1])
        for item in data_spectra.get("totalDataChart", [])
    }

    rows = []
    for dt, revenue in hl_chart.items():
        if START_DATE <= dt <= TARGET_DATE:
            rows.append({"date": dt, "revenue": max(0, revenue - spectra_chart.get(dt, 0))})

    df = pd.DataFrame(rows).set_index("date").sort_index()
    hip4_df = get_hip4_prediction_market_revenue_history()
    if not hip4_df.empty:
        df = pd.merge(df, hip4_df, left_index=True, right_index=True, how="outer")
        df["revenue"] = df["revenue"].fillna(0) + df["hip4_prediction_revenue"].fillna(0)
        df = df[["revenue"]].sort_index()
    return df


def linear_unlocked(dt, amount, start, end):
    if dt <= start:
        return 0.0
    if dt >= end:
        return float(amount)
    return float(amount) * ((dt - start) / (end - start))


def schedule_circulating_supply(dt):
    supply = GENESIS_DISTRIBUTION if dt >= START_DATE else 0.0
    supply += linear_unlocked(dt, FUTURE_COMMUNITY_REWARDS, START_DATE, SIXTY_MONTH_VEST_END)
    supply += linear_unlocked(dt, HYPER_FOUNDATION_BUDGET, START_DATE, SIXTY_MONTH_VEST_END)
    supply += linear_unlocked(dt, CORE_CONTRIBUTORS, TWELVE_MONTH_CLIFF, THIRTY_SIX_MONTH_VEST_END)
    supply += linear_unlocked(dt, COMMUNITY_GRANTS, TWELVE_MONTH_CLIFF, THIRTY_SIX_MONTH_VEST_END)
    return min(supply, TOTAL_HYPE_SUPPLY)


def get_hype_market_cap_history(hype_df, revenue_df):
    print("Calculating HYPE circulating supply from unlock schedule, net of buyback/burn...")
    full_index = hype_df[(hype_df.index >= START_DATE) & (hype_df.index <= TARGET_DATE)].index
    schedule_df = pd.DataFrame(index=full_index)
    schedule_df["hype_circulating_supply"] = [
        schedule_circulating_supply(dt) for dt in schedule_df.index
    ]

    buyback_df = pd.merge(
        hype_df[["HYPE_price"]],
        revenue_df[["revenue"]],
        left_index=True,
        right_index=True,
        how="left",
    ).reindex(full_index)
    buyback_df["daily_buyback_burn_hype"] = buyback_df["revenue"].fillna(0) / buyback_df["HYPE_price"]
    schedule_df["cumulative_buyback_burn_hype"] = buyback_df["daily_buyback_burn_hype"].cumsum()
    schedule_df["hype_circulating_supply"] = (
        schedule_df["hype_circulating_supply"] - schedule_df["cumulative_buyback_burn_hype"]
    ).clip(lower=0)
    schedule_df["hype_market_cap"] = hype_df.loc[full_index, "HYPE_price"] * schedule_df["hype_circulating_supply"]
    print(
        "  Cumulative buyback/burn through "
        f"{schedule_df.index.max().date()}: {schedule_df['cumulative_buyback_burn_hype'].iloc[-1]:,.0f} HYPE"
    )
    return schedule_df.sort_index(), "HYPE spot price x (schedule-unlocked supply - cumulative revenue/price buyback-burn)"


def plot_combined_data(hype_df, btc_df, revenue_df, market_cap_df, market_cap_source):
    print("Generating TGE-to-now multi-asset plot...")
    full_index = pd.date_range(START_DATE, TARGET_DATE, freq="D")
    df = pd.DataFrame(index=full_index)
    for source_df in (hype_df, btc_df, revenue_df, market_cap_df):
        df = pd.merge(df, source_df, left_index=True, right_index=True, how="left")

    if df.empty:
        raise RuntimeError("No overlapping data found for HYPE, BTC, revenue, and market cap.")

    df["revenue_7d_avg"] = df["revenue"].rolling(window=7, min_periods=7).mean()
    df["hype_ps_ratio"] = df["hype_market_cap"] / (df["revenue_7d_avg"] * 365)

    fig, ax1 = plt.subplots(figsize=(15, 8))
    plt.subplots_adjust(right=0.80)

    color_rev = "#1f77b4"
    ax1.set_xlabel("Date")
    ax1.set_ylabel("Daily Revenue (USD)", color=color_rev, fontsize=11, fontweight="bold")
    ax1.plot(df.index, df["revenue"], color=color_rev, alpha=0.2, label="Daily Revenue")
    ax1.plot(df.index, df["revenue_7d_avg"], color=color_rev, linewidth=2, label="Revenue (7d Avg)")
    ax1.tick_params(axis="y", labelcolor=color_rev)
    ax1.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"${x / 1e6:.1f}M" if x >= 1e6 else f"${x:,.0f}")
    )
    ax1.grid(True, which="both", linestyle="--", alpha=0.3)

    ax2 = ax1.twinx()
    color_hype = "#2ca02c"
    ax2.set_ylabel("HYPE Price (USD)", color=color_hype, fontsize=11, fontweight="bold")
    ax2.plot(df.index, df["HYPE_price"], color=color_hype, linewidth=2.5, label="HYPE Price")
    ax2.tick_params(axis="y", labelcolor=color_hype)

    ax3 = ax1.twinx()
    ax3.spines["right"].set_position(("outward", 60))
    color_btc = "#ff7f0e"
    ax3.set_ylabel("BTC Price (USD)", color=color_btc, fontsize=11, fontweight="bold")
    ax3.plot(df.index, df["BTC_price"], color=color_btc, linewidth=1.5, linestyle=":", label="BTC Price")
    ax3.tick_params(axis="y", labelcolor=color_btc)
    ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x / 1e3:.0f}k"))

    ax4 = ax1.twinx()
    ax4.spines["right"].set_position(("outward", 120))
    color_ps = "#9467bd"
    ax4.set_ylabel("HYPE P/S (7d revenue annualized)", color=color_ps, fontsize=11, fontweight="bold")
    ax4.plot(df.index, df["hype_ps_ratio"], color=color_ps, linewidth=2, linestyle="-.", label="HYPE P/S")
    ax4.tick_params(axis="y", labelcolor=color_ps)
    ax4.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}x"))

    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.set_xlim(START_DATE, TARGET_DATE)
    plt.xticks(rotation=0)

    plt.title("Hyperliquid Macro Trend Since $HYPE TGE: Revenue, $HYPE, BTC, and P/S", fontsize=14, pad=25)
    fig.text(0.01, 0.01, f"P/S market cap source: {market_cap_source}", fontsize=8, color="#555555")

    handles, labels = [], []
    for axis in (ax1, ax2, ax3, ax4):
        axis_handles, axis_labels = axis.get_legend_handles_labels()
        handles += axis_handles
        labels += axis_labels
    ax1.legend(handles, labels, loc="upper left", frameon=True, shadow=True)

    plt.tight_layout()
    plt.savefig(OUTPUT_PATH, dpi=150)
    print(f"Multi-asset chart saved as: {OUTPUT_PATH}")
    print(f"Date range plotted: {df.index.min().date()} to {df.index.max().date()} ({len(df)} calendar days)")
    print(f"First revenue point: {df['revenue'].first_valid_index().date()}")


if __name__ == "__main__":
    hype = get_sdk_price_history("HYPE", candle_symbol="@107")
    btc = get_sdk_price_history("BTC")
    revenue = get_protocol_revenue_history()
    market_cap, market_cap_source = get_hype_market_cap_history(hype, revenue)
    plot_combined_data(hype, btc, revenue, market_cap, market_cap_source)
