"""Render dashboard.html from the daily brief markdown + interactive macro chart.

Uses the `markdown` package to convert the brief into HTML and `plotly` to draw
an interactive 6M macro-trend chart sourced from the local sqlite DB.
"""
from __future__ import annotations

import math
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import markdown as md_lib
import pandas as pd
import plotly.graph_objects as go
import requests

from aqa import fetch_aqa_payouts

STABLECOIN_CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/Hyperliquid%20L1"
COINGECKO_COIN_IDS = {"hype": "hyperliquid", "bnb": "binancecoin"}

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
DB_PATH = ROOT / "data" / "hyperliquid_stats.db"
OUTPUT_PATH = ROOT / "output" / "dashboard.html"

MD_EXTENSIONS = ["tables", "sane_lists"]

# --- AQA (Aligned Quote Asset) USDC reserve-income (off-protocol, NOT in revenue_daily) ---
# Actual payouts are read live from the Assistance Fund ledger (fetch_aqa_payouts()); this dict
# is the model used for forward scenarios and as the fallback when the HL API fetch fails.
# See logs/2026-07-24-coinbase-usdc-reserve-income-research.md,
# logs/2026-08-17-aqav2-gitbook-confirmation.md and logs/2026-10-12-aqav2-first-payout.md
# before changing these numbers. Mechanism per the official docs
# (hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets): accrued daily at
# 0 UTC, settled in 30-day intervals, paid to the Assistance Fund 8 days after each interval.
USDC_ESTIMATE = {
    "as_of": "2026-10-12",
    "float_usd": 6.176e9,         # Coinbase's own AQAv2 activation post (2026-06-08): USDC reserves
                                   # at activation, 95.06% of Hyperliquid L1 stablecoins
    "hl_share": 0.90,              # official docs: ~90% of "cost-adjusted reserve yield revenue"
                                    # remitted to the protocol (net of issuer costs, not gross)
    # Calibrated to the first actual payout ($14.58M for 2026-08-26..09-25 on a $7.03B avg
    # DefiLlama float => 2.52% net => ~2.80% gross-equivalent at 90%). Was 3.0/3.5/4.0%, which
    # overstated the payout by ~25% on the live float. When payouts are available the Base
    # rate is re-derived live from the latest payout (aqa_calibration()).
    "yield_low": 0.025,
    "yield_base": 0.028,
    "yield_high": 0.031,
    "accrual_start": "2026-08-26",
    "interval_days": 30,
    "settle_days": 8,
}


def latest_brief() -> Path:
    # Plain YYYY-MM-DD.md only — excludes suffixed research/analysis notes like
    # YYYY-MM-DD-revenue-breakdown.md, which sort after same-day briefs and would
    # otherwise get picked up as "latest" and fail date parsing downstream.
    candidates = sorted(
        p for p in LOGS_DIR.glob("20*-*-*.md")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)
    )
    if not candidates:
        raise FileNotFoundError("No daily brief markdown found in logs/")
    return candidates[-1]


def normalize_brief(md_text: str) -> str:
    """Make the brief's tight formatting parser-friendly.

    - Promote standalone `**Heading**` lines to `### Heading` so they render
      as section headers instead of inline-bold paragraphs.
    - Insert a blank line before tables/lists so block parsing kicks in.
    """
    raw_lines = md_text.splitlines()
    promoted: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if (
            stripped.startswith("**")
            and stripped.endswith("**")
            and stripped.count("**") == 2
            and len(stripped) > 4
        ):
            promoted.append(f"### {stripped[2:-2]}")
        else:
            promoted.append(line)

    out: list[str] = []
    for line in promoted:
        prev = out[-1] if out else ""
        is_table = line.lstrip().startswith("|")
        is_list = line.lstrip().startswith("- ")
        starts_block = is_table or is_list
        if starts_block and prev.strip() and not (
            prev.lstrip().startswith("|") or prev.lstrip().startswith("- ")
        ):
            out.append("")
        out.append(line)
    return "\n".join(out)


def load_metrics(end_date: str | None = None) -> pd.DataFrame:
    """Load all daily_metrics rows up to and including `end_date`."""
    if not DB_PATH.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            "SELECT date, hype_price, btc_price, bnb_price, revenue_daily, "
            "revenue_7d_avg, hype_ps_ratio, hype_ps_ratio_incl_aqa, hype_market_cap "
            "FROM daily_metrics ORDER BY date ASC",
            conn,
            parse_dates=["date"],
        )
    finally:
        conn.close()
    if df.empty:
        return df
    if end_date:
        cutoff = pd.to_datetime(end_date)
        df = df[df["date"] <= cutoff]
    return df.reset_index(drop=True)


def build_interactive_chart(df: pd.DataFrame) -> str:
    """Return an HTML fragment with an interactive plotly chart.

    Layout mirrors the static matplotlib version: revenue on the left axis,
    HYPE / BTC / P/S spread out on the right with progressively offset positions
    so labels stay readable.
    """
    if df.empty:
        return '<p style="color:var(--ink-3)">No metrics in DB yet.</p>'

    color_rev = "#0B6E4F"
    color_hype = "#1A4FA8"
    color_btc = "#8A5C00"
    color_ps = "#7A3DAA"
    color_bnb = "#C2185B"
    grid = "rgba(24,24,15,0.08)"
    ink = "#18180F"
    ink_3 = "#8A897E"

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df["date"], y=df["revenue_daily"],
        name="Daily Revenue",
        marker=dict(color=color_rev, opacity=0.22),
        yaxis="y1",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Revenue: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["revenue_7d_avg"],
        name="Revenue 7d Avg",
        mode="lines",
        line=dict(color=color_rev, width=2.2),
        yaxis="y1",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Rev 7d: $%{y:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["hype_price"],
        name="HYPE Price",
        mode="lines",
        line=dict(color=color_hype, width=2.6),
        yaxis="y2",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>HYPE: $%{y:,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["btc_price"],
        name="BTC Price",
        mode="lines",
        line=dict(color=color_btc, width=1.6, dash="dot"),
        yaxis="y3",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>BTC: $%{y:,.0f}<extra></extra>",
    ))
    if df["bnb_price"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["bnb_price"],
            name="BNB Price",
            mode="lines",
            line=dict(color=color_bnb, width=1.6, dash="dash"),
            yaxis="y5",
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>BNB: $%{y:,.0f}<extra></extra>",
        ))
    if df["hype_ps_ratio"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["hype_ps_ratio"],
            name="HYPE P/S (on-chain)",
            mode="lines",
            line=dict(color=color_ps, width=1.6, dash="dashdot"),
            yaxis="y4",
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>P/S on-chain: %{y:.1f}x<extra></extra>",
        ))
    if df["hype_ps_ratio_incl_aqa"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["hype_ps_ratio_incl_aqa"],
            name="HYPE P/S (incl. AQAv2)",
            mode="lines",
            line=dict(color=color_ps, width=2.2),
            yaxis="y4",
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>P/S incl. AQAv2: %{y:.1f}x<extra></extra>",
        ))

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(
            family="'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
            color=ink, size=12,
        ),
        margin=dict(l=80, r=90, t=140, b=70),
        height=620,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.03,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)",
            font=dict(size=11, color=ink_3),
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#FFFFFF", bordercolor="#D8D5CA",
            font=dict(family="'IBM Plex Mono', monospace", size=11, color=ink),
        ),
        xaxis=dict(
            domain=[0.0, 0.70],
            range=[
                (df["date"].max() - pd.Timedelta(days=180)).isoformat(),
                df["date"].max().isoformat(),
            ],
            rangeslider=dict(
                visible=True,
                thickness=0.08,
                bgcolor="#FFFFFF",
                bordercolor="#C5C2B5",
                borderwidth=1,
            ),
            rangeselector=dict(
                buttons=[
                    dict(count=7, label="1W", step="day", stepmode="backward"),
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(step="all", label="ALL"),
                ],
                bgcolor="#EFEDE6", activecolor="#1A4FA8",
                bordercolor="#D8D5CA", borderwidth=1,
                font=dict(color=ink, size=11,
                          family="'IBM Plex Mono', monospace"),
                x=0, y=1.2, xanchor="left", yanchor="bottom",
            ),
            gridcolor=grid,
            linecolor="#D8D5CA", showline=True, mirror=False,
            tickfont=dict(family="'IBM Plex Mono', monospace", size=11, color=ink_3),
        ),
        yaxis=dict(
            title=dict(text="Daily Revenue (USD)",
                       font=dict(color=color_rev, size=12)),
            tickprefix="$", tickformat=".2s",
            gridcolor=grid, zeroline=False,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_rev),
        ),
        yaxis2=dict(
            title=dict(text="HYPE Price (USD)",
                       font=dict(color=color_hype, size=12)),
            tickprefix="$", tickformat=",.2f",
            overlaying="y", side="right", anchor="x",
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_hype),
            showgrid=False, zeroline=False,
        ),
        yaxis3=dict(
            title=dict(text="BTC Price",
                       font=dict(color=color_btc, size=12)),
            tickprefix="$", tickformat=".2s",
            overlaying="y", side="right", anchor="free", position=0.80,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_btc),
            showgrid=False, zeroline=False,
        ),
        yaxis4=dict(
            title=dict(text="HYPE P/S",
                       font=dict(color=color_ps, size=12)),
            ticksuffix="x", tickformat=".0f",
            overlaying="y", side="right", anchor="free", position=0.90,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_ps),
            showgrid=False, zeroline=False,
        ),
        yaxis5=dict(
            title=dict(text="BNB Price",
                       font=dict(color=color_bnb, size=12)),
            tickprefix="$", tickformat=".2s",
            overlaying="y", side="right", anchor="free", position=1.0,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_bnb),
            showgrid=False, zeroline=False,
        ),
    )

    return fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={"displaylogo": False, "responsive": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
        div_id="macro-chart",
    )


def fetch_usdc_float_series() -> pd.DataFrame:
    """Fetch the daily pegged-stablecoin circulating supply on Hyperliquid L1 from
    DefiLlama's stablecoins API. This is the float that drives AQAv2 reserve income
    (float x yield x share) -- a balance/stock metric, not trading volume. USDC is
    ~95%+ of this total (see logs/2026-07-24-coinbase-usdc-reserve-income-research.md),
    so summing all pegged assets on the chain is a close, continuously-live proxy for
    "USDC on Hyperliquid" without needing per-asset filtering.
    """
    try:
        resp = requests.get(STABLECOIN_CHART_URL, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as exc:
        print(f"USDC float fetch failed: {exc}", file=sys.stderr)
        return pd.DataFrame(columns=["date", "circulating_usd"])

    records = []
    for row in rows:
        pegged = row.get("totalCirculatingUSD", {})
        if not pegged:
            continue
        records.append({
            "date": pd.to_datetime(int(row["date"]), unit="s"),
            "circulating_usd": sum(pegged.values()),
        })
    df = pd.DataFrame.from_records(records)
    if df.empty:
        return df
    return df.sort_values("date").reset_index(drop=True)


def fetch_coin_market_stats(coin_id: str) -> dict:
    """Fetch current USD price and fully-diluted valuation for a CoinGecko coin id.

    Returns {"price": float | None, "fdv": float | None}. On any failure both
    are None so the dashboard build can render a live-fetch failure
    gracefully (as an em dash in the UI) instead of crashing.
    """
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    params = {
        "localization": "false", "tickers": "false", "market_data": "true",
        "community_data": "false", "developer_data": "false", "sparkline": "false",
    }
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        market_data = resp.json()["market_data"]
        return {
            "price": market_data.get("current_price", {}).get("usd"),
            "fdv": market_data.get("fully_diluted_valuation", {}).get("usd"),
        }
    except Exception as exc:
        print(f"CoinGecko market stats fetch failed for {coin_id}: {exc}", file=sys.stderr)
        return {"price": None, "fdv": None}


def build_fdv_stats_html(hype_stats: dict, bnb_stats: dict) -> str:
    """Render a small live stat row: HYPE/BNB price + fully-diluted valuation.

    Supplements the brief's own static, once-daily Valuation table with a
    couple of live-refreshed CoinGecko figures. Missing values (fetch
    failure) render as an em dash rather than raising.
    """
    def fmt_usd(v):
        if v is None:
            return "—"
        if v >= 1e9:
            return f"${v / 1e9:,.2f}B"
        if v >= 1e6:
            return f"${v / 1e6:,.1f}M"
        return f"${v:,.2f}"

    return f"""
    <div class="fdv-stats">
      <div class="estimate-flag">LIVE &middot; CoinGecko</div>
      <div class="readout-grid">
        <div class="readout-card"><div class="lbl">HYPE Price</div><div class="val">{fmt_usd(hype_stats['price'])}</div></div>
        <div class="readout-card"><div class="lbl">HYPE FDV</div><div class="val">{fmt_usd(hype_stats['fdv'])}</div></div>
        <div class="readout-card"><div class="lbl">BNB Price</div><div class="val">{fmt_usd(bnb_stats['price'])}</div></div>
        <div class="readout-card"><div class="lbl">BNB FDV</div><div class="val">{fmt_usd(bnb_stats['fdv'])}</div></div>
      </div>
    </div>
"""


def build_usdc_float_chart_html(df: pd.DataFrame) -> str:
    """Small line chart: USDC(+other pegged stablecoins) circulating on Hyperliquid L1,
    daily, DefiLlama-sourced, live. This is the float that AQAv2 reserve income scales
    off of -- included alongside the AQA estimate card as the directly-observable input,
    since the estimate itself has no live feed for the float otherwise.
    """
    if df.empty:
        return '<p style="color:var(--ink-3)">USDC float series unavailable (fetch failed) -- see stderr.</p>'

    color_float = "#1A4FA8"
    grid = "rgba(24,24,15,0.08)"
    ink = "#18180F"
    ink_3 = "#8A897E"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["circulating_usd"] / 1e9,
        name="USDC (+other pegged) circulating",
        mode="lines",
        line=dict(color=color_float, width=2.2),
        fill="tozeroy", fillcolor="rgba(26,79,168,0.08)",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Float: $%{y:.2f}B<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        font=dict(family="'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
                  color=ink, size=12),
        margin=dict(l=70, r=20, t=10, b=50),
        height=280,
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#D8D5CA",
                         font=dict(family="'IBM Plex Mono', monospace", size=11, color=ink)),
        xaxis=dict(
            range=[
                (df["date"].max() - pd.Timedelta(days=180)).isoformat(),
                df["date"].max().isoformat(),
            ],
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(step="all", label="ALL"),
                ],
                bgcolor="#EFEDE6", activecolor="#1A4FA8",
                bordercolor="#D8D5CA", borderwidth=1,
                font=dict(color=ink, size=10, family="'IBM Plex Mono', monospace"),
                x=0, y=1.16, xanchor="left", yanchor="top",
            ),
            gridcolor=grid, linecolor="#D8D5CA", showline=True,
            tickfont=dict(family="'IBM Plex Mono', monospace", size=10, color=ink_3),
        ),
        yaxis=dict(
            tickprefix="$", ticksuffix="B", tickformat=".1f",
            gridcolor=grid, zeroline=False,
            tickfont=dict(family="'IBM Plex Mono', monospace", size=10, color=ink_3),
        ),
    )
    return fig.to_html(
        include_plotlyjs=False,
        full_html=False,
        config={"displaylogo": False, "responsive": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
        div_id="usdc-float-chart",
    )


def render_brief(md_text: str) -> tuple[str, str]:
    """Return (title, body_html). The leading `# Title` line becomes the title."""
    lines = md_text.splitlines()
    title = ""
    body_lines = list(lines)
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            body_lines = lines[:idx] + lines[idx + 1:]
            break
    body_md = normalize_brief("\n".join(body_lines))
    body_html = md_lib.markdown(body_md, extensions=MD_EXTENSIONS)
    return title, body_html


def aqa_calibration(payouts: list[dict] | None, float_df: pd.DataFrame) -> dict | None:
    """Realized AQAv2 rate from the latest actual payout: payout x 365/30 divided by the
    average DefiLlama float over that payout's accrual interval. The result is a *net* rate
    (already after the issuer's ~10% cut and costs); `gross_equiv` divides back by hl_share
    for comparison with the old 3.0-4.0% gross yield assumption. None if no payout yet or the
    float series is unavailable."""
    if not payouts or float_df.empty:
        return None
    last = payouts[-1]
    mask = ((float_df["date"] >= pd.Timestamp(last["interval_start"]))
            & (float_df["date"] < pd.Timestamp(last["interval_end"])))
    if not mask.any():
        return None
    avg_float = float(float_df.loc[mask, "circulating_usd"].mean())
    net_rate = last["annualized_usd"] / avg_float
    return {"last": last, "avg_float": avg_float, "net_rate": net_rate,
            "gross_equiv": net_rate / USDC_ESTIMATE["hl_share"]}


def aqa_scenarios(float_usd: float, calib: dict | None) -> list[tuple[str, float, float]]:
    """(label, gross-equivalent yield, annualized $) for Low/Base/High on `float_usd`.
    Base uses the realized rate when a payout exists; Low/High are +/-0.3pp around it."""
    e = USDC_ESTIMATE
    base = calib["gross_equiv"] if calib else e["yield_base"]
    if calib:
        low, high = base - 0.003, base + 0.003
    else:
        low, high = e["yield_low"], e["yield_high"]
    return [(label, y, float_usd * y * e["hl_share"])
            for label, y in (("Low", low), ("Base", base), ("High", high))]


def build_usdc_estimate_html(live_float_usd: float | None = None,
                             payouts: list[dict] | None = None,
                             calib: dict | None = None) -> str:
    """Render the AQAv2 (Aligned Quote Asset) USDC reserve-income card: actual payouts to
    the Assistance Fund (read live from the HL ledger via aqa.fetch_aqa_payouts()), the
    realized rate they imply, and forward run-rate scenarios on the live float.

    This income is NOT in revenue_daily / revenue_7d_avg / hype_ps_ratio (DefiLlama doesn't
    track it); it IS in hype_ps_ratio_incl_aqa (latest payout x 365/30, see aqa.py). It funds
    the Assistance Fund's HYPE buybacks, separate from HLP/vault yield paid to depositors.
    See logs/2026-10-12-aqav2-first-payout.md and logs/2026-08-17-aqav2-gitbook-confirmation.md.
    """
    e = USDC_ESTIMATE
    float_usd = live_float_usd if live_float_usd is not None else e["float_usd"]

    def fmt_usd(v: float) -> str:
        return f"${v / 1e6:,.1f}M" if v >= 1e6 else f"${v:,.0f}"

    if payouts is None:
        payout_html = '<p style="color:var(--ink-3)">AQA payout fetch failed (HL API) -- see stderr.</p>'
    elif not payouts:
        payout_html = '<p style="color:var(--ink-3)">No AQAv2 payout to the Assistance Fund yet.</p>'
    else:
        payout_rows = "\n".join(
            f'''      <tr class="{'is-base' if p is payouts[-1] else ''}">
        <td>{p['paid_date']}</td><td>{p['interval_start']} &rarr; {p['interval_end'] - timedelta(days=1)}</td>
        <td>{fmt_usd(p['amount_usd'])}</td><td>${p['amount_usd'] / 30 / 1e3:,.0f}K</td><td>{fmt_usd(p['annualized_usd'])}</td>
      </tr>'''
            for p in reversed(payouts)
        )
        payout_html = f"""
      <table class="estimate-table">
        <thead><tr><th>Paid (UTC)</th><th>Accrual interval</th><th>Payout</th><th>Per day</th><th>Annualized (&times;365/30)</th></tr></thead>
        <tbody>
{payout_rows}
        </tbody>
      </table>"""

    calib_html = ""
    if calib:
        calib_html = f"""
      <p class="estimate-note">Realized rate (latest payout): {fmt_usd(calib['last']['annualized_usd'])}/yr
      &divide; ${calib['avg_float']/1e9:.2f}B average float over {calib['last']['interval_start']} &rarr;
      {calib['last']['interval_end'] - timedelta(days=1)} = <strong>{calib['net_rate']:.2%} net</strong>
      (&asymp;{calib['gross_equiv']:.2%} gross-equivalent at {e['hl_share']:.0%} share). The earlier 3.5% gross
      assumption overstated this by ~25% on the live float; the scenarios below are re-centered on the
      realized rate.</p>"""

    scen_rows = "\n".join(
        f'''      <tr class="{'is-base' if label == 'Base' else ''}">
        <td>{label}</td><td>{y:.2%}</td>
        <td>{fmt_usd(annual)}</td><td>{fmt_usd(annual * 30 / 365)}</td><td>${annual / 365 / 1e3:,.1f}K</td>
      </tr>'''
        for label, y, annual in aqa_scenarios(float_usd, calib)
    )

    return f"""
    <div class="estimate-card">
      <div class="estimate-flag">ACTUAL PAYOUTS &middot; HL ledger &middot; not in revenue_daily, included in P/S incl. AQAv2</div>
      <p>Hyperliquid's <strong>AQAv2 (Aligned Quote Asset)</strong> program: Coinbase/Circle remit
      <strong>~{e['hl_share']:.0%}</strong> of the cost-adjusted reserve yield on USDC held on Hyperliquid
      to the protocol. Per the official docs it is <strong>accrued daily at 0 UTC</strong>, settled in
      <strong>{e['interval_days']}-day intervals</strong> (from {e['accrual_start']}), and paid to the
      <strong>Assistance Fund</strong> {e['settle_days']} days after each interval closes &mdash; so it lands
      on-chain as one lump per month, as a system send of USDC from
      <span class="mono">0x5000&hellip;0000</span> to the Assistance Fund
      (<span class="mono">0xfefe&hellip;fefe</span>), which funds open-market <strong>$HYPE buybacks</strong>.
      DefiLlama does not count it, so it is absent from <span class="mono">revenue_daily</span>; the
      headline P/S adds the latest payout annualized (&times;365/30) on top of on-chain revenue.</p>
{payout_html}
{calib_html}
      <table class="estimate-table">
        <thead><tr><th>Run-rate scenario</th><th>Gross-equiv. yield</th><th>Annualized</th><th>Per 30-day payout</th><th>Daily</th></tr></thead>
        <tbody>
{scen_rows}
        </tbody>
      </table>
      <p class="estimate-note">Scenarios apply to the live float (${float_usd/1e9:.2f}B, DefiLlama pegged-stablecoin
      supply on Hyperliquid L1, USDC ~95%+ of it, chart above) and estimate the <em>next</em> payout; the P/S
      itself uses the last actual payout, not a scenario. Because the float includes ~5% non-USDC stablecoins,
      the realized rate per USDC is slightly higher than shown. Mechanism confirmed by
      hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets; first payout matched the
      documented Aug 26 + 30d + 8d schedule.</p>
    </div>
"""


def latest_ps_inputs() -> dict:
    """Pull the latest price/supply/revenue figures needed to seed the P/S explorer."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT date, hype_price, hype_circulating_supply, "
            "revenue_7d_avg, revenue_30d_avg "
            "FROM daily_metrics WHERE hype_price IS NOT NULL "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"as_of": None, "price": 60.0, "circ_supply": 222_445_714.0,
                "protocol_rev_7d": 328_000_000.0, "protocol_rev_30d": 385_000_000.0}
    as_of, price, circ_supply, rev_7d_avg, rev_30d_avg = row
    return {
        "as_of": as_of,
        "price": float(price),
        "circ_supply": float(circ_supply),
        "protocol_rev_7d": float(rev_7d_avg) * 365,
        "protocol_rev_30d": float(rev_30d_avg) * 365,
    }


def build_ps_explorer_html(live_float_usd: float | None = None, calib: dict | None = None) -> str:
    """Render the interactive $HYPE P/S explorer: protocol revenue, AQAv2 revenue,
    and price as independently-draggable parameters, with P/S computed live in-browser.

    Modeled on the K4.3 explorer pattern from the CRCL deep-dive report
    (stock_eval/circle/CRCL_deepdive_2026-07-21_v2.html): paired slider+number inputs
    per parameter, a draggable 2D heatmap (price x AQA revenue, colored by P/S) with a
    crosshair for the current state, and live readout cards. Protocol revenue is a third,
    independent slider (not a heatmap axis) so its effect can be explored without
    conflating it with the AQA/price surface — same "decouple the axes" principle CRCL
    used for its yield slider.

    The AQA slider defaults to the latest actual payout annualized (same figure the headline
    "P/S incl. AQAv2" uses) when `calib` is available; Low/Base/High presets are the run-rate
    scenarios from aqa_scenarios() on the live DefiLlama float. See
    build_usdc_estimate_html() and logs/2026-10-12-aqav2-first-payout.md.
    """
    inputs = latest_ps_inputs()
    e = USDC_ESTIMATE
    float_usd = live_float_usd if live_float_usd is not None else e["float_usd"]
    (_, y_low, aqa_low), (_, y_base, aqa_base), (_, y_high, aqa_high) = aqa_scenarios(float_usd, calib)
    aqa_actual = calib["last"]["annualized_usd"] if calib else None
    aqa_default = aqa_actual if aqa_actual is not None else aqa_base
    actual_btn = (f'<button type="button" class="mini-btn" data-aqa="{aqa_actual/1e6:.1f}">Actual (latest)</button>\n            '
                  if aqa_actual is not None else "")

    # Slider ceiling scales with the data so the 7D/30D presets never get clamped.
    prot_max = max(1500, math.ceil(max(inputs["protocol_rev_7d"], inputs["protocol_rev_30d"]) * 1.5 / 1e8) * 100)

    as_of_note = f"as of {inputs['as_of']}" if inputs["as_of"] else "no DB rows found, using fallback defaults"

    return f"""
    <div class="ps-explorer">
      <div class="estimate-flag">INTERACTIVE &middot; illustrative, not a tracked metric</div>
      <p>Drag the heatmap to set <strong>HYPE price</strong> and <strong>AQAv2 revenue</strong>
      together, or use the sliders/number inputs for precise values. <strong>Protocol revenue</strong>
      is a separate, independent slider &mdash; it shifts the whole P/S surface without being a
      heatmap axis itself, so you can isolate its effect from the price/AQA tradeoff. P/S here is
      <span class="mono">market cap &divide; annualized revenue</span>, where market cap uses the
      circulating supply {as_of_note} ({inputs['circ_supply']/1e6:,.1f}M HYPE) &times; the price
      you set. AQAv2 revenue is never in DefiLlama's tracked <span class="mono">revenue_daily</span>
      but it is real cash paid to the Assistance Fund monthly; the AQA slider defaults to the
      latest actual payout &times; 365/30, the same figure behind the headline P/S incl. AQAv2.</p>

      <div class="ctrl-grid">
        <div class="ctrl-group">
          <label>Hyperliquid Protocol Revenue (annualized) <span class="val" id="pse-protocol-val">$328M</span></label>
          <input type="range" id="pse-protocol" min="100" max="{prot_max}" step="1" value="{inputs['protocol_rev_7d']/1e6:.0f}">
          <div class="ctrl-sub">Enter: $<input type="number" id="pse-protocol-num" min="100" max="{prot_max}" step="1" value="{inputs['protocol_rev_7d']/1e6:.0f}">M
            &middot; <button type="button" class="mini-btn" data-protocol="{inputs['protocol_rev_7d']/1e6:.1f}">7D avg&times;365</button>
            <button type="button" class="mini-btn" data-protocol="{inputs['protocol_rev_30d']/1e6:.1f}">30D avg&times;365</button></div>
        </div>
        <div class="ctrl-group">
          <label>AQAv2 Revenue (annualized) <span class="val" id="pse-aqa-val">${aqa_default/1e6:.0f}M</span></label>
          <input type="range" id="pse-aqa" min="0" max="300" step="1" value="{aqa_default/1e6:.0f}">
          <div class="ctrl-sub">Enter: $<input type="number" id="pse-aqa-num" min="0" max="300" step="1" value="{aqa_default/1e6:.0f}">M
            &middot; {actual_btn}<button type="button" class="mini-btn" data-aqa="{aqa_low/1e6:.1f}">Low</button>
            <button type="button" class="mini-btn" data-aqa="{aqa_base/1e6:.1f}">Base</button>
            <button type="button" class="mini-btn" data-aqa="{aqa_high/1e6:.1f}">High</button>
            <button type="button" class="mini-btn" data-aqa="0">Off</button></div>
        </div>
        <div class="ctrl-group">
          <label>HYPE Price <span class="val" id="pse-price-val">${inputs['price']:.2f}</span></label>
          <input type="range" id="pse-price" min="20" max="150" step="0.5" value="{inputs['price']:.2f}">
          <div class="ctrl-sub">Enter: $<input type="number" id="pse-price-num" min="20" max="150" step="0.5" value="{inputs['price']:.2f}">
            &middot; <button type="button" class="mini-btn" data-price="40">$40</button>
            <button type="button" class="mini-btn" data-price="50">$50</button>
            <button type="button" class="mini-btn" data-price="60">$60</button>
            <button type="button" class="mini-btn" data-price="70">$70</button>
            <button type="button" class="mini-btn" data-price="80">$80</button></div>
        </div>
      </div>

      <div class="readout-grid">
        <div class="readout-card"><div class="lbl">Market Cap</div><div class="val" id="pse-out-mcap">&mdash;</div></div>
        <div class="readout-card"><div class="lbl">Total Annualized Revenue</div><div class="val" id="pse-out-rev">&mdash;</div></div>
        <div class="readout-card"><div class="lbl">P/S (on-chain only)</div><div class="val" id="pse-out-ps-base">&mdash;</div></div>
        <div class="readout-card hero"><div class="lbl">P/S (on-chain + AQA)</div><div class="val" id="pse-out-ps-combined">&mdash;</div></div>
      </div>

      <div class="heatmap-wrap">
        <svg id="pse-heatmap" width="720" height="360" viewBox="0 0 720 360"></svg>
        <div class="hm-legend"><span>P/S &le;15x (cheap)</span><span class="bar bar-ps"></span><span>P/S &ge;45x (expensive)</span></div>
      </div>
      <p class="estimate-note">Heatmap: X axis = HYPE price, Y axis = AQAv2 annualized revenue, color = P/S (current protocol-revenue slider value + that cell's AQA revenue); the crosshair marks the current price/AQA slider values and can be dragged directly.
      Circulating supply and 7D/30D protocol-revenue baselines {as_of_note}; AQAv2 default = latest actual payout &times; 365/30; Low/Base/High = live USDC float ${float_usd/1e9:.3f}B (DefiLlama) &times; {y_low:.2%}/{y_base:.2%}/{y_high:.2%} gross yield &times; {e['hl_share']:.0%} share (Base calibrated to actual payouts).
      Purely an interactive estimation tool; nothing here is written to the database.</p>
    </div>
    <script>
    (function(){{
      var CIRC = {inputs['circ_supply']!r};  // circulating HYPE supply, {as_of_note}
      var PROT_MIN = 100, PROT_MAX = {prot_max};
      var PRICE_MIN = 20, PRICE_MAX = 150, PRICE_STEP = 5;
      var AQA_MIN = 0, AQA_MAX = 300, AQA_STEP = 15;
      var PS_LOW = 15, PS_MID = 30, PS_HIGH = 45;

      function clamp(v,lo,hi){{ return Math.min(hi, Math.max(lo, v)); }}
      function fmtUSD(v){{ return v >= 1e9 ? '$' + (v/1e9).toFixed(2) + 'B' : '$' + (v/1e6).toFixed(1) + 'M'; }}
      function fmtPS(v){{ return v.toFixed(1) + 'x'; }}

      function mcap(price){{ return price * CIRC; }}
      function ps(price, protocolM, aqaM){{ return mcap(price) / ((protocolM + aqaM) * 1e6); }}

      var protocolSlider = document.getElementById('pse-protocol');
      var protocolNum = document.getElementById('pse-protocol-num');
      var protocolVal = document.getElementById('pse-protocol-val');
      var aqaSlider = document.getElementById('pse-aqa');
      var aqaNum = document.getElementById('pse-aqa-num');
      var aqaVal = document.getElementById('pse-aqa-val');
      var priceSlider = document.getElementById('pse-price');
      var priceNum = document.getElementById('pse-price-num');
      var priceVal = document.getElementById('pse-price-val');
      var outMcap = document.getElementById('pse-out-mcap');
      var outRev = document.getElementById('pse-out-rev');
      var outPsBase = document.getElementById('pse-out-ps-base');
      var outPsCombined = document.getElementById('pse-out-ps-combined');
      var svg = document.getElementById('pse-heatmap');

      var state = {{
        protocol: parseFloat(protocolSlider.value),
        aqa: parseFloat(aqaSlider.value),
        price: parseFloat(priceSlider.value)
      }};

      protocolSlider.addEventListener('input', function(){{ state.protocol = clamp(parseFloat(protocolSlider.value), PROT_MIN, PROT_MAX); protocolNum.value = state.protocol.toFixed(0); render(); }});
      protocolNum.addEventListener('input', function(){{ if(protocolNum.value==='') return; state.protocol = clamp(parseFloat(protocolNum.value), PROT_MIN, PROT_MAX); protocolSlider.value = state.protocol; render(); }});
      aqaSlider.addEventListener('input', function(){{ state.aqa = clamp(parseFloat(aqaSlider.value), AQA_MIN, AQA_MAX); aqaNum.value = state.aqa.toFixed(0); render(); }});
      aqaNum.addEventListener('input', function(){{ if(aqaNum.value==='') return; state.aqa = clamp(parseFloat(aqaNum.value), AQA_MIN, AQA_MAX); aqaSlider.value = state.aqa; render(); }});
      priceSlider.addEventListener('input', function(){{ state.price = clamp(parseFloat(priceSlider.value), PRICE_MIN, PRICE_MAX); priceNum.value = state.price.toFixed(2); render(); }});
      priceNum.addEventListener('input', function(){{ if(priceNum.value==='') return; state.price = clamp(parseFloat(priceNum.value), PRICE_MIN, PRICE_MAX); priceSlider.value = state.price; render(); }});

      document.querySelectorAll('.mini-btn[data-protocol]').forEach(function(btn){{
        btn.addEventListener('click', function(){{ state.protocol = parseFloat(btn.getAttribute('data-protocol')); protocolSlider.value = clamp(state.protocol, PROT_MIN, PROT_MAX); protocolNum.value = state.protocol.toFixed(1); render(); }});
      }});
      document.querySelectorAll('.mini-btn[data-aqa]').forEach(function(btn){{
        btn.addEventListener('click', function(){{ state.aqa = parseFloat(btn.getAttribute('data-aqa')); aqaSlider.value = clamp(state.aqa,AQA_MIN,AQA_MAX); aqaNum.value = state.aqa.toFixed(1); render(); }});
      }});
      document.querySelectorAll('.mini-btn[data-price]').forEach(function(btn){{
        btn.addEventListener('click', function(){{ state.price = parseFloat(btn.getAttribute('data-price')); priceSlider.value = state.price; priceNum.value = state.price.toFixed(2); render(); }});
      }});

      var PAD = {{l:44,r:14,t:12,b:32}};
      var W = 720, H = 360;
      var plotW = W-PAD.l-PAD.r, plotH = H-PAD.t-PAD.b;
      function gx(p){{ return PAD.l + (p-PRICE_MIN)/(PRICE_MAX-PRICE_MIN)*plotW; }}
      function gy(a){{ return PAD.t + (1-(a-AQA_MIN)/(AQA_MAX-AQA_MIN))*plotH; }}
      function gInv(px){{ return PRICE_MIN + (px-PAD.l)/plotW*(PRICE_MAX-PRICE_MIN); }}
      function aInv(py){{ return AQA_MIN + (1-(py-PAD.t)/plotH)*(AQA_MAX-AQA_MIN); }}

      function colorForPS(v){{
        var good=[11,110,79], warn=[138,92,0], bad=[184,51,38];
        var t = clamp((v-PS_LOW)/(PS_HIGH-PS_LOW), 0, 1);
        var c;
        if(t<0.5){{ var tt=t*2; c=[good[0]+(warn[0]-good[0])*tt, good[1]+(warn[1]-good[1])*tt, good[2]+(warn[2]-good[2])*tt]; }}
        else {{ var tt2=(t-0.5)*2; c=[warn[0]+(bad[0]-warn[0])*tt2, warn[1]+(bad[1]-warn[1])*tt2, warn[2]+(bad[2]-warn[2])*tt2]; }}
        return 'rgb(' + c.map(Math.round).join(',') + ')';
      }}

      var built = false;
      function buildHeatmap(){{
        var ns = 'http://www.w3.org/2000/svg';
        var cellW = plotW/((PRICE_MAX-PRICE_MIN)/PRICE_STEP), cellH = plotH/((AQA_MAX-AQA_MIN)/AQA_STEP);
        for(var p=PRICE_MIN; p<PRICE_MAX; p+=PRICE_STEP){{
          for(var a=AQA_MIN; a<AQA_MAX; a+=AQA_STEP){{
            var pc = p+PRICE_STEP/2, ac = a+AQA_STEP/2;
            var r = document.createElementNS(ns,'rect');
            r.setAttribute('x', gx(p)); r.setAttribute('y', gy(a+AQA_STEP));
            r.setAttribute('width', cellW+0.6); r.setAttribute('height', cellH+0.6);
            r.setAttribute('data-p', pc); r.setAttribute('data-a', ac);
            r.setAttribute('class','hm-cell');
            svg.appendChild(r);
          }}
        }}
        var axisColor = '#8A897E';
        for(var pt=PRICE_MIN; pt<=PRICE_MAX; pt+=20){{
          var t = document.createElementNS(ns,'text');
          t.setAttribute('x', gx(pt)); t.setAttribute('y', H-PAD.b+16);
          t.setAttribute('font-size','10'); t.setAttribute('fill', axisColor); t.setAttribute('text-anchor','middle');
          t.textContent = '$'+pt; svg.appendChild(t);
        }}
        for(var at=AQA_MIN; at<=AQA_MAX; at+=50){{
          var t2 = document.createElementNS(ns,'text');
          t2.setAttribute('x', PAD.l-6); t2.setAttribute('y', gy(at)+3);
          t2.setAttribute('font-size','10'); t2.setAttribute('fill', axisColor); t2.setAttribute('text-anchor','end');
          t2.textContent = '$'+at+'M'; svg.appendChild(t2);
        }}
        var xlab = document.createElementNS(ns,'text');
        xlab.setAttribute('x', PAD.l+plotW/2); xlab.setAttribute('y', H-4);
        xlab.setAttribute('font-size','11'); xlab.setAttribute('font-weight','700'); xlab.setAttribute('fill', axisColor); xlab.setAttribute('text-anchor','middle');
        xlab.textContent = 'HYPE Price \\u2192'; svg.appendChild(xlab);
        var ylab = document.createElementNS(ns,'text');
        ylab.setAttribute('x', 8); ylab.setAttribute('y', PAD.t+10);
        ylab.setAttribute('font-size','11'); ylab.setAttribute('font-weight','700'); ylab.setAttribute('fill', axisColor);
        ylab.textContent = 'AQA \\u2191'; svg.appendChild(ylab);

        var cross = document.createElementNS(ns,'g');
        var hLine = document.createElementNS(ns,'line');
        hLine.setAttribute('id','pse-hline'); hLine.setAttribute('stroke','#18180F'); hLine.setAttribute('stroke-width','1'); hLine.setAttribute('stroke-dasharray','3,3'); hLine.setAttribute('opacity','0.55');
        var vLine = document.createElementNS(ns,'line');
        vLine.setAttribute('id','pse-vline'); vLine.setAttribute('stroke','#18180F'); vLine.setAttribute('stroke-width','1'); vLine.setAttribute('stroke-dasharray','3,3'); vLine.setAttribute('opacity','0.55');
        var dot = document.createElementNS(ns,'circle');
        dot.setAttribute('id','pse-dot'); dot.setAttribute('r','6'); dot.setAttribute('fill','#1A4FA8'); dot.setAttribute('stroke','#fff'); dot.setAttribute('stroke-width','2');
        cross.appendChild(hLine); cross.appendChild(vLine); cross.appendChild(dot);
        svg.appendChild(cross);

        function handlePointer(evt){{
          var rect = svg.getBoundingClientRect();
          var clientX = evt.touches ? evt.touches[0].clientX : evt.clientX;
          var clientY = evt.touches ? evt.touches[0].clientY : evt.clientY;
          var px = (clientX-rect.left) * (W/rect.width);
          var py = (clientY-rect.top) * (H/rect.height);
          state.price = clamp(gInv(px), PRICE_MIN, PRICE_MAX);
          state.aqa = clamp(aInv(py), AQA_MIN, AQA_MAX);
          priceSlider.value = state.price; priceNum.value = state.price.toFixed(2);
          aqaSlider.value = state.aqa; aqaNum.value = state.aqa.toFixed(1);
          render();
        }}
        var dragging = false;
        svg.addEventListener('mousedown', function(e){{ dragging = true; handlePointer(e); }});
        window.addEventListener('mousemove', function(e){{ if(dragging) handlePointer(e); }});
        window.addEventListener('mouseup', function(){{ dragging = false; }});
        svg.addEventListener('touchstart', function(e){{ handlePointer(e); e.preventDefault(); }}, {{passive:false}});
        svg.addEventListener('touchmove', function(e){{ handlePointer(e); e.preventDefault(); }}, {{passive:false}});
        built = true;
      }}

      function render(){{
        if(!built) buildHeatmap();
        protocolVal.textContent = fmtUSD(state.protocol*1e6);
        aqaVal.textContent = fmtUSD(state.aqa*1e6);
        priceVal.textContent = '$'+state.price.toFixed(2);

        var mc = mcap(state.price);
        var totalRev = (state.protocol + state.aqa) * 1e6;
        var psBase = mc / (state.protocol*1e6);
        var psCombined = mc / totalRev;

        outMcap.textContent = fmtUSD(mc);
        outRev.textContent = fmtUSD(totalRev);
        outPsBase.textContent = fmtPS(psBase);
        outPsCombined.textContent = fmtPS(psCombined);

        var cells = svg.querySelectorAll('.hm-cell');
        for(var i=0;i<cells.length;i++){{
          var cell = cells[i];
          var pc = parseFloat(cell.getAttribute('data-p')), ac = parseFloat(cell.getAttribute('data-a'));
          cell.setAttribute('fill', colorForPS(ps(pc, state.protocol, ac)));
        }}
        var dot = document.getElementById('pse-dot');
        var hLine = document.getElementById('pse-hline');
        var vLine = document.getElementById('pse-vline');
        var px = gx(state.price), py = gy(state.aqa);
        dot.setAttribute('cx', px); dot.setAttribute('cy', py);
        hLine.setAttribute('x1', PAD.l); hLine.setAttribute('x2', W-PAD.r); hLine.setAttribute('y1', py); hLine.setAttribute('y2', py);
        vLine.setAttribute('x1', px); vLine.setAttribute('x2', px); vLine.setAttribute('y1', PAD.t); vLine.setAttribute('y2', H-PAD.b);
      }}

      render();
    }})();
    </script>
"""


CSS = """
*,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #F8F7F3;
  --bg-2: #EFEDE6;
  --bg-3: #E6E3DA;
  --ink: #18180F;
  --ink-2: #4A4940;
  --ink-3: #8A897E;
  --pos: #0B6E4F;
  --pos-bg: #E6F4EE;
  --neg: #B83326;
  --neg-bg: #F9ECEA;
  --amber: #8A5C00;
  --amber-bg: #FDF4E0;
  --blue: #1A4FA8;
  --blue-bg: #EAF0FA;
  --border: #D8D5CA;
  --border-2: #C5C2B5;
  --radius: 6px;
  --radius-lg: 10px;
  --font-body: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', ui-monospace, Menlo, monospace;
}
body { background: var(--bg); color: var(--ink); font-family: var(--font-body);
  font-size: 14px; line-height: 1.6; padding: 0 0 64px; }
.page { max-width: 1180px; margin: 0 auto; padding: 0 28px; }

.report-header { border-bottom: 2px solid var(--ink); padding: 36px 0 24px; }
.report-eyebrow { font-family: var(--font-mono); font-size: 11px;
  color: var(--ink-3); letter-spacing: .1em; text-transform: uppercase;
  margin-bottom: 10px; }
.report-title { font-size: 28px; font-weight: 600; letter-spacing: -.02em;
  line-height: 1.2; margin-bottom: 6px; }
.report-subtitle { font-size: 14px; color: var(--ink-2); font-weight: 300; }
.report-meta { display: flex; flex-wrap: wrap; gap: 24px; margin-top: 20px;
  padding-top: 16px; border-top: 1px solid var(--border); }
.report-meta span { font-family: var(--font-mono); font-size: 11px;
  color: var(--ink-3); }
.report-meta strong { color: var(--ink); font-weight: 500; }

.section { margin-top: 40px; }
.section-head { display: flex; align-items: baseline; gap: 12px;
  margin-bottom: 18px; padding-bottom: 10px;
  border-bottom: 1px solid var(--border); }
.section-num { font-family: var(--font-mono); font-size: 11px;
  color: var(--ink-3); font-weight: 400; }
.section-title { font-size: 17px; font-weight: 600; letter-spacing: -.01em; }

.chart-card { background: #FFFFFF; border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 18px 18px 12px; }
.chart-card .card-title { font-size: 11px; font-weight: 500;
  text-transform: uppercase; letter-spacing: .07em; color: var(--ink-3);
  margin-bottom: 6px; font-family: var(--font-mono); }
.chart-card .card-hint { font-size: 11px; color: var(--ink-3);
  margin-bottom: 8px; }
.chart-card .plotly-graph-div { width: 100% !important; }

/* Highlight selected window: shadow the UNSELECTED portions of the rangeslider
   and outline the selected box so the active range is unmistakable. */
.chart-card .rangeslider-mask-min,
.chart-card .rangeslider-mask-max {
  fill: rgba(24, 24, 15, 0.32) !important;
}
.chart-card .rangeslider-slidebox {
  fill: rgba(26, 79, 168, 0.10) !important;
  stroke: #1A4FA8 !important;
  stroke-width: 1.5px !important;
}
.chart-card .rangeslider-grabber-min rect,
.chart-card .rangeslider-grabber-max rect {
  fill: #1A4FA8 !important;
}

.brief-card { background: #FFFFFF; border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 24px 28px; }
.brief-card h3 { font-family: var(--font-mono); font-size: 11px;
  font-weight: 500; color: var(--ink-3); text-transform: uppercase;
  letter-spacing: .07em; margin: 22px 0 10px; }
.brief-card h3:first-child { margin-top: 0; }
.brief-card p { margin: 8px 0; line-height: 1.65; color: var(--ink-2); }
.brief-card ul { margin: 8px 0 0; padding-left: 18px; }
.brief-card li { margin: 8px 0; line-height: 1.65; color: var(--ink-2); }
.brief-card li strong { color: var(--ink); font-weight: 500; }
.brief-card blockquote { margin: 18px 0 0; padding: 10px 14px;
  background: var(--bg-2); border-radius: var(--radius);
  color: var(--ink-3); font-size: 12px; border: none; }
.brief-card blockquote p { margin: 0; color: var(--ink-3); }
.fdv-stats { margin-top: 14px; }

.brief-card table { width: 100%; border-collapse: collapse; font-size: 12px;
  margin: 4px 0 14px; font-family: var(--font-mono); }
.brief-card th { font-size: 10px; text-transform: uppercase;
  letter-spacing: .07em; color: var(--ink-3); font-weight: 400;
  text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border-2);
  background: var(--bg-2); }
.brief-card td { padding: 8px 10px; color: var(--ink-2); font-size: 11.5px;
  border-bottom: 1px solid var(--border); }
.brief-card tbody tr:last-child td { border-bottom: none; }
.brief-card td strong { color: var(--ink); font-weight: 500;
  font-family: var(--font-body); }

.estimate-card { background: #FFFFFF; border: 1px solid var(--amber);
  border-radius: var(--radius-lg); padding: 22px 26px; }
.estimate-flag { display: inline-block; font-family: var(--font-mono);
  font-size: 10px; font-weight: 500; text-transform: uppercase;
  letter-spacing: .07em; color: var(--amber); background: var(--amber-bg);
  border-radius: 4px; padding: 4px 9px; margin-bottom: 12px; }
.estimate-card p { margin: 10px 0; line-height: 1.65; color: var(--ink-2);
  font-size: 13px; }
.estimate-card p:first-of-type { margin-top: 0; }
.estimate-table { width: 100%; border-collapse: collapse; font-size: 12px;
  margin: 14px 0; font-family: var(--font-mono); }
.estimate-table th { font-size: 10px; text-transform: uppercase;
  letter-spacing: .07em; color: var(--ink-3); font-weight: 400;
  text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border-2);
  background: var(--bg-2); }
.estimate-table td { padding: 8px 10px; color: var(--ink-2);
  border-bottom: 1px solid var(--border); }
.estimate-table tbody tr:last-child td { border-bottom: none; }
.estimate-table tr.is-base td { color: var(--ink); font-weight: 500;
  background: var(--amber-bg); }
.estimate-note { font-size: 11.5px !important; color: var(--ink-3) !important; }

.report-footer { margin-top: 48px; padding-top: 18px;
  border-top: 1px solid var(--border); display: flex;
  justify-content: space-between; align-items: center; }
.footer-note { font-family: var(--font-mono); font-size: 10px;
  color: var(--ink-3); }

.mono { font-family: var(--font-mono); }

.ps-explorer { background: #FFFFFF; border: 1px solid var(--blue);
  border-radius: var(--radius-lg); padding: 22px 26px; }
.ps-explorer p { margin: 10px 0; line-height: 1.65; color: var(--ink-2); font-size: 13px; }
.ps-explorer p:first-of-type { margin-top: 0; }
.ps-explorer .estimate-flag { color: var(--blue); background: var(--blue-bg); }

.ctrl-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 18px 22px; margin: 18px 0; }
.ctrl-group label { display: block; font-size: 12px; font-weight: 500;
  color: var(--ink); margin-bottom: 6px; }
.ctrl-group label .val { font-family: var(--font-mono); font-weight: 500;
  color: var(--blue); float: right; }
.ctrl-group input[type="range"] { width: 100%; accent-color: #1A4FA8; }
.ctrl-sub { font-size: 11px; color: var(--ink-3); margin-top: 6px;
  display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.ctrl-sub input[type="number"] { width: 62px; font-family: var(--font-mono);
  font-size: 11px; padding: 3px 5px; border: 1px solid var(--border-2);
  border-radius: 4px; background: var(--bg); color: var(--ink); }
.mini-btn { font-family: var(--font-mono); font-size: 10px; padding: 3px 8px;
  border: 1px solid var(--border-2); border-radius: 4px; background: var(--bg-2);
  color: var(--ink-2); cursor: pointer; }
.mini-btn:hover { background: var(--blue-bg); border-color: var(--blue); color: var(--blue); }

.readout-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px; margin: 18px 0; }
.readout-card { background: var(--bg-2); border-radius: var(--radius);
  padding: 12px 14px; text-align: center; }
.readout-card.hero { background: var(--blue-bg); border: 1px solid var(--blue); }
.readout-card .lbl { font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--ink-3); margin-bottom: 6px; }
.readout-card .val { font-family: var(--font-mono); font-size: 18px; font-weight: 500;
  color: var(--ink); }
.readout-card.hero .val { color: var(--blue); font-size: 22px; }

.heatmap-wrap { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.heatmap-wrap svg { width: 100%; max-width: 720px; height: auto;
  border: 1px solid var(--border); border-radius: var(--radius); cursor: crosshair; }
.hm-cell { stroke: none; }
.hm-legend { display: flex; align-items: center; gap: 8px; font-size: 10px;
  color: var(--ink-3); font-family: var(--font-mono); }
.hm-legend .bar-ps { width: 120px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg, #0B6E4F, #8A5C00, #B83326); }
"""


def build_html(title: str, body_html: str, chart_html: str, brief_path: Path,
               row_count: int, usdc_float_chart_html: str, usdc_estimate_html: str,
               ps_explorer_html: str, fdv_stats_html: str) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    safe_title = title or "Hyperliquid Dashboard"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{safe_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="page">

  <header class="report-header">
    <div class="report-eyebrow">Hyperliquid Daily Report &middot; $HYPE Morning Brief</div>
    <h1 class="report-title">{safe_title}</h1>
    <p class="report-subtitle">Price action, protocol revenue, and valuation snapshot for the Hyperliquid ecosystem.</p>
    <div class="report-meta">
      <span>Source <strong>{brief_path.name}</strong></span>
      <span>Series <strong>{row_count} daily rows</strong></span>
      <span>Generated <strong>{generated} UTC</strong></span>
      <span>Cadence <strong>04:00 UTC</strong></span>
    </div>
  </header>

  <section class="section">
    <div class="section-head">
      <span class="section-num">01</span>
      <h2 class="section-title">6M Macro Trend</h2>
    </div>
    <div class="chart-card">
      <div class="card-title">HYPE / BTC / Revenue / P-S &middot; daily, last 180 days</div>
      <div class="card-hint">Drag to zoom &middot; double-click to reset &middot; click legend to toggle &middot; range buttons + slider below.</div>
      {chart_html}
    </div>
  </section>

  <section class="section">
    <div class="section-head">
      <span class="section-num">02</span>
      <h2 class="section-title">Morning Brief</h2>
    </div>
    <div class="brief-card">
{body_html}
    </div>
    {fdv_stats_html}
  </section>

  <section class="section">
    <div class="section-head">
      <span class="section-num">03</span>
      <h2 class="section-title">USDC Reserve Income (AQA / AQAv2) &mdash; Actual Payouts &amp; Run-Rate</h2>
    </div>
    <div class="chart-card" style="margin-bottom:18px;">
      <div class="card-title">USDC (+other pegged stablecoins) circulating on Hyperliquid L1 &middot; DefiLlama, daily</div>
      <div class="card-hint">This is the float AQAv2 reserve income scales off of &mdash; a balance, not trading volume. Drag to zoom &middot; range buttons above chart.</div>
      {usdc_float_chart_html}
    </div>
    {usdc_estimate_html}
  </section>

  <section class="section">
    <div class="section-head">
      <span class="section-num">04</span>
      <h2 class="section-title">$HYPE P/S Explorer &mdash; Protocol Revenue &times; AQAv2 &times; Price</h2>
    </div>
    {ps_explorer_html}
  </section>

  <footer class="report-footer">
    <span class="footer-note">Auto-refreshed daily at 04:00 UTC.</span>
    <span class="footer-note">Data analysis only, not financial advice.</span>
  </footer>
</div>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        brief_path = LOGS_DIR / f"{argv[1]}.md"
        if not brief_path.exists():
            print(f"Brief not found: {brief_path}", file=sys.stderr)
            return 1
    else:
        brief_path = latest_brief()

    md_text = brief_path.read_text(encoding="utf-8")
    title, body_html = render_brief(md_text)
    end_date = brief_path.stem
    df = load_metrics(end_date=end_date)
    chart_html = build_interactive_chart(df)

    usdc_float_df = fetch_usdc_float_series()
    live_float_usd = float(usdc_float_df["circulating_usd"].iloc[-1]) if not usdc_float_df.empty else None
    usdc_float_chart_html = build_usdc_float_chart_html(usdc_float_df)
    aqa_payouts = fetch_aqa_payouts()
    calib = aqa_calibration(aqa_payouts, usdc_float_df)
    usdc_estimate_html = build_usdc_estimate_html(live_float_usd, aqa_payouts, calib)
    ps_explorer_html = build_ps_explorer_html(live_float_usd, calib)

    hype_stats = fetch_coin_market_stats(COINGECKO_COIN_IDS["hype"])
    bnb_stats = fetch_coin_market_stats(COINGECKO_COIN_IDS["bnb"])
    fdv_stats_html = build_fdv_stats_html(hype_stats, bnb_stats)

    html = build_html(title, body_html, chart_html, brief_path, len(df),
                       usdc_float_chart_html, usdc_estimate_html, ps_explorer_html,
                       fdv_stats_html)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
