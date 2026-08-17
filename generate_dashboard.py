"""Render dashboard.html from the daily brief markdown + interactive macro chart.

Uses the `markdown` package to convert the brief into HTML and `plotly` to draw
an interactive 6M macro-trend chart sourced from the local sqlite DB.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import markdown as md_lib
import pandas as pd
import plotly.graph_objects as go
import requests

STABLECOIN_CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/Hyperliquid%20L1"

ROOT = Path(__file__).resolve().parent
LOGS_DIR = ROOT / "logs"
DB_PATH = ROOT / "hyperliquid_stats.db"
OUTPUT_PATH = ROOT / "dashboard.html"

MD_EXTENSIONS = ["tables", "sane_lists"]

# --- AQA (Aligned Quote Asset) USDC reserve-income estimate (off-protocol, NOT in revenue_daily) ---
# Manual estimate, not a live feed. See logs/2026-07-24-coinbase-usdc-reserve-income-research.md,
# logs/2026-07-24-usdc-revenue-vs-user-yield-research.md, and
# logs/2026-08-17-aqav2-gitbook-confirmation.md for full sourcing/methodology and caveats before
# changing these numbers. The 90% share and accrual timeline are now confirmed by the official
# docs (hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets), not just
# secondary reporting.
USDC_ESTIMATE = {
    "as_of": "2026-07-24",
    "float_usd": 6.176e9,         # Coinbase's own AQAv2 activation post (2026-06-08): USDC reserves
                                   # at activation, 95.06% of Hyperliquid L1 stablecoins
    "hl_share": 0.90,              # official docs: ~90% of "cost-adjusted reserve yield revenue"
                                    # remitted to the protocol (net of issuer costs, not gross)
    "yield_low": 0.030,
    "yield_base": 0.035,           # derived from Circle Q1'26 reserve income / avg circulating USDC
    "yield_high": 0.040,
    "accrual_start": "2026-08-26", # official mechanism: 30-day accrual intervals + 8-day settlement
    "first_payment": "2026-10-03", # lag to Assistance Fund; confirmed by BlockBeats 2026-08-17
                                    # (19/26 validator approval) matching the math exactly
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
            "SELECT date, hype_price, btc_price, revenue_daily, "
            "revenue_7d_avg, hype_ps_ratio, hype_market_cap "
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
    if df["hype_ps_ratio"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["hype_ps_ratio"],
            name="HYPE P/S",
            mode="lines",
            line=dict(color=color_ps, width=1.6, dash="dashdot"),
            yaxis="y4",
            hovertemplate="<b>%{x|%Y-%m-%d}</b><br>P/S: %{y:.1f}x<extra></extra>",
        ))

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(
            family="'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
            color=ink, size=12,
        ),
        margin=dict(l=80, r=170, t=70, b=70),
        height=560,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.06,
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
            domain=[0.0, 0.86],
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
                x=0, y=1.18, xanchor="left", yanchor="top",
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
            overlaying="y", side="right", anchor="free", position=0.93,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_btc),
            showgrid=False, zeroline=False,
        ),
        yaxis4=dict(
            title=dict(text="HYPE P/S",
                       font=dict(color=color_ps, size=12)),
            ticksuffix="x", tickformat=".0f",
            overlaying="y", side="right", anchor="free", position=1.0,
            tickfont=dict(family="'IBM Plex Mono', monospace",
                          size=11, color=color_ps),
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
        x=df["date"], y=df["circulating_usd"],
        name="USDC (+other pegged) circulating",
        mode="lines",
        line=dict(color=color_float, width=2.2),
        fill="tozeroy", fillcolor="rgba(26,79,168,0.08)",
        hovertemplate="<b>%{x|%Y-%m-%d}</b><br>Float: $%{y:,.0f}<extra></extra>",
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
            tickprefix="$", tickformat=".2s",
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


def build_usdc_estimate_html(live_float_usd: float | None = None) -> str:
    """Render the AQA (Aligned Quote Asset) USDC reserve-income estimate card.

    This is NOT on-chain protocol revenue and is NOT included in revenue_daily,
    revenue_7d_avg, or hype_ps_ratio anywhere else in this dashboard/DB — it's
    an off-chain interest-income split between Coinbase/Circle and Hyperliquid
    (the AQA/AQAv2 program), confirmed absent from ASXN's own rev-fee-breakdown
    taxonomy. It funds the Hyperliquid Assistance Fund's HYPE buybacks directly,
    separately from HLP/vault yield paid to individual USDC depositors — see the
    research log for why those are parallel, non-overlapping mechanisms.

    `live_float_usd`, when provided (from fetch_usdc_float_series(), DefiLlama's daily
    pegged-stablecoin-on-Hyperliquid-L1 series), replaces the static Coinbase-post float
    ($6.176B as of 2026-06-08) in the yield-scenario table below, so the estimate tracks
    the float as it actually moves instead of staying pinned to a single announcement-day
    snapshot. The yield assumption itself is still a manual, undisclosed-rate estimate —
    see logs/2026-07-24-coinbase-usdc-reserve-income-research.md and
    logs/2026-07-24-usdc-revenue-vs-user-yield-research.md.
    """
    e = USDC_ESTIMATE
    float_usd = live_float_usd if live_float_usd is not None else e["float_usd"]
    rows = []
    for label, y in (("Low", e["yield_low"]), ("Base", e["yield_base"]), ("High", e["yield_high"])):
        annual = float_usd * y * e["hl_share"]
        monthly = annual / 12
        daily = annual / 365.25
        rows.append((label, y, annual, monthly, daily))

    def fmt_usd(v: float) -> str:
        return f"${v / 1e6:,.1f}M" if v >= 1e6 else f"${v:,.0f}"

    def fmt_usd_k(v: float) -> str:
        return f"${v / 1e3:,.1f}K"

    row_html = "\n".join(
        f'''      <tr class="{'is-base' if label == 'Base' else ''}">
        <td>{label}</td><td>{y:.1%}</td>
        <td>{fmt_usd(annual)}</td><td>{fmt_usd(monthly)}</td><td>{fmt_usd_k(daily)}</td>
      </tr>'''
        for label, y, annual, monthly, daily in rows
    )

    return f"""
    <div class="estimate-card">
      <div class="estimate-flag">ESTIMATE &middot; off-protocol &middot; not in revenue_daily</div>
      <p>Hyperliquid's <strong>AQA (Aligned Quote Asset)</strong> program, upgraded to
      <strong>AQAv2</strong>, designates USDC as the primary margin/spot/perp asset on Hyperliquid.
      Under it, Coinbase classifies USDC held on Hyperliquid as &quot;on-platform&quot;, collecting
      the reserve income it generates and paying <strong>~90%</strong> of that income back to
      Hyperliquid (Coinbase keeps the remaining ~10%, net of the issuer's own costs &mdash; the
      official docs specify &quot;cost-adjusted reserve yield revenue&quot;). Per Coinbase's own
      AQAv2 activation announcement (2026-06-08), USDC reserves stood at
      <strong>${e['float_usd']/1e9:.2f}B</strong> when the float was classified &quot;on-platform&quot;
      &mdash; &asymp;8% of USDC's global circulating supply at the time, and 95.06% of Hyperliquid
      L1's own stablecoin base. The chart above tracks this float live via DefiLlama
      (pegged-stablecoin supply on &quot;Hyperliquid L1&quot;, USDC is ~95%+ of it) &mdash;
      <strong>${float_usd/1e9:.2f}B</strong> as of the latest data point below, a reasonable
      cross-check against Coinbase's own figure two months on. The scenario table uses this
      live number, not the frozen June figure. Validator-approved protocol-level accrual begins
      <strong>{e['accrual_start']}</strong> (30-day accrual intervals, paid 8 days after each interval
      closes), with the first Assistance Fund payment expected <strong>{e['first_payment']}</strong>.
      A future network upgrade will make AQAv2 <strong>mandatory</strong> for quote assets on HIP-4
      and validator-operated perp markets, extending this beyond USDC/Coinbase. This income is
      routed to the <strong>Hyperliquid Assistance Fund</strong>, which executes open-market
      <strong>$HYPE buybacks</strong> &mdash; it is separate from, and additive to, tracked protocol
      fee revenue. No live feed exists for this &mdash; this is a manual, clearly-bounded estimate,
      not a tracked metric.</p>
      <table class="estimate-table">
        <thead><tr><th>Scenario</th><th>Yield</th><th>Annualized</th><th>Monthly</th><th>Daily</th></tr></thead>
        <tbody>
{row_html}
        </tbody>
      </table>
      <p class="estimate-note">Yield assumption (3.0&ndash;4.0%, base 3.5%) is derived, not disclosed:
      Circle's own Q1'26 reserve income ($653M) &divide; ~$76.15B average circulating USDC
      &asymp; 3.4% annualized, used as a proxy for this float's yield &mdash; roughly consistent
      with the Fed funds target range at the time (3.50&ndash;3.75%), and likely a slight
      overstatement since the official 90% share applies to yield net of issuer costs, not gross.
      The 90% share and accrual mechanics are now confirmed by Hyperliquid's own docs
      (hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets), corroborated by
      19/26 validator approval and a $4.4B Circle&rarr;Coinbase USDC restaging on HyperEVM reported
      2026-08-17 &mdash; stronger footing than the secondary-outlet-only framing (CoinDesk,
      CryptoBriefing, Bankless, Coinbase's activation post) this estimate started from. The prior
      Jun 8 vs. Aug 26 accrual-date disagreement is resolved: Jun 8 was Coinbase's own
      &quot;on-platform&quot; classification date (float existed, no protocol-level accrual yet);
      {e['accrual_start']} is when validator-approved AQAv2 accrual actually begins, with first
      Assistance Fund payment {e['first_payment']} &mdash; math confirmed by the docs' own 30-day
      accrual + 8-day settlement mechanism. Confirmed via ASXN's own compiled JS that this income
      has no path into Hyperliquid's on-chain fee revenue at all. Float is live (DefiLlama,
      refreshed on every dashboard build); Coinbase's own ${e['float_usd']/1e9:.2f}B figure is as
      of {e['as_of']}; mechanism/dates as of 2026-08-17.</p>
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


def build_ps_explorer_html(live_float_usd: float | None = None) -> str:
    """Render the interactive $HYPE P/S explorer: protocol revenue, AQAv2 revenue,
    and price as independently-draggable parameters, with P/S computed live in-browser.

    Modeled on the K4.3 explorer pattern from the CRCL deep-dive report
    (stock_eval/circle/CRCL_deepdive_2026-07-21_v2.html): paired slider+number inputs
    per parameter, a draggable 2D heatmap (price x AQA revenue, colored by P/S) with a
    crosshair for the current state, and live readout cards. Protocol revenue is a third,
    independent slider (not a heatmap axis) so its effect can be explored without
    conflating it with the AQA/price surface — same "decouple the axes" principle CRCL
    used for its yield slider.

    `live_float_usd`, when provided, seeds the AQA Low/Base/High preset buttons off the
    live DefiLlama float (see fetch_usdc_float_series()) instead of the static Coinbase
    figure in USDC_ESTIMATE. See build_usdc_estimate_html() docstring and
    logs/2026-08-17-aqav2-gitbook-confirmation.md for sourcing.
    """
    inputs = latest_ps_inputs()
    e = USDC_ESTIMATE
    float_usd = live_float_usd if live_float_usd is not None else e["float_usd"]
    aqa_low = float_usd * e["yield_low"] * e["hl_share"]
    aqa_base = float_usd * e["yield_base"] * e["hl_share"]
    aqa_high = float_usd * e["yield_high"] * e["hl_share"]

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
      &mdash; this tool exists to show what P/S looks like if you count it anyway. See
      logs/2026-08-17-aqav2-gitbook-confirmation.md for the AQA mechanism/sourcing.</p>

      <div class="ctrl-grid">
        <div class="ctrl-group">
          <label>Hyperliquid Protocol Revenue (annualized) <span class="val" id="pse-protocol-val">$328M</span></label>
          <input type="range" id="pse-protocol" min="100" max="700" step="1" value="{inputs['protocol_rev_7d']/1e6:.0f}">
          <div class="ctrl-sub">直接输入: $<input type="number" id="pse-protocol-num" min="100" max="700" step="1" value="{inputs['protocol_rev_7d']/1e6:.0f}">M
            &middot; <button type="button" class="mini-btn" data-protocol="{inputs['protocol_rev_7d']/1e6:.1f}">7D avg&times;365</button>
            <button type="button" class="mini-btn" data-protocol="{inputs['protocol_rev_30d']/1e6:.1f}">30D avg&times;365</button></div>
        </div>
        <div class="ctrl-group">
          <label>AQAv2 Revenue (annualized) <span class="val" id="pse-aqa-val">$195M</span></label>
          <input type="range" id="pse-aqa" min="0" max="300" step="1" value="{aqa_base/1e6:.0f}">
          <div class="ctrl-sub">直接输入: $<input type="number" id="pse-aqa-num" min="0" max="300" step="1" value="{aqa_base/1e6:.0f}">M
            &middot; <button type="button" class="mini-btn" data-aqa="{aqa_low/1e6:.1f}">Low</button>
            <button type="button" class="mini-btn" data-aqa="{aqa_base/1e6:.1f}">Base</button>
            <button type="button" class="mini-btn" data-aqa="{aqa_high/1e6:.1f}">High</button>
            <button type="button" class="mini-btn" data-aqa="0">Off</button></div>
        </div>
        <div class="ctrl-group">
          <label>HYPE Price <span class="val" id="pse-price-val">${inputs['price']:.2f}</span></label>
          <input type="range" id="pse-price" min="20" max="150" step="0.5" value="{inputs['price']:.2f}">
          <div class="ctrl-sub">直接输入: $<input type="number" id="pse-price-num" min="20" max="150" step="0.5" value="{inputs['price']:.2f}">
            &middot; <button type="button" class="mini-btn" data-price="40">$40</button>
            <button type="button" class="mini-btn" data-price="50">$50</button>
            <button type="button" class="mini-btn" data-price="60">$60</button>
            <button type="button" class="mini-btn" data-price="70">$70</button>
            <button type="button" class="mini-btn" data-price="80">$80</button></div>
        </div>
      </div>

      <div class="readout-grid">
        <div class="readout-card"><div class="lbl">市值</div><div class="val" id="pse-out-mcap">&mdash;</div></div>
        <div class="readout-card"><div class="lbl">合计年化收入</div><div class="val" id="pse-out-rev">&mdash;</div></div>
        <div class="readout-card"><div class="lbl">P/S(仅链上)</div><div class="val" id="pse-out-ps-base">&mdash;</div></div>
        <div class="readout-card hero"><div class="lbl">P/S(链上+AQA)</div><div class="val" id="pse-out-ps-combined">&mdash;</div></div>
      </div>

      <div class="heatmap-wrap">
        <svg id="pse-heatmap" width="720" height="360" viewBox="0 0 720 360"></svg>
        <div class="hm-legend"><span>P/S &le;15x(便宜)</span><span class="bar bar-ps"></span><span>P/S &ge;45x(贵)</span></div>
      </div>
      <p class="estimate-note">热力图: X轴 = HYPE价格, Y轴 = AQAv2年化收入, 颜色 = P/S(链上协议收入滑块的当前值 + 该格AQA收入); 十字标记 = 当前价格/AQA滑块读数, 可直接拖动定位。
      流通量、7D/30D协议收入基准 {as_of_note}; AQAv2 Low/Base/High = 实时USDC浮存量 ${float_usd/1e9:.3f}B(DefiLlama) &times; 3.0/3.5/4.0% yield &times; {e['hl_share']:.0%} share。
      纯粹是交互式估算工具, 不写入任何数据库字段。</p>
    </div>
    <script>
    (function(){{
      var CIRC = {inputs['circ_supply']!r};  // circulating HYPE supply, {as_of_note}
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

      protocolSlider.addEventListener('input', function(){{ state.protocol = clamp(parseFloat(protocolSlider.value), 100, 700); protocolNum.value = state.protocol.toFixed(0); render(); }});
      protocolNum.addEventListener('input', function(){{ if(protocolNum.value==='') return; state.protocol = clamp(parseFloat(protocolNum.value), 100, 700); protocolSlider.value = state.protocol; render(); }});
      aqaSlider.addEventListener('input', function(){{ state.aqa = clamp(parseFloat(aqaSlider.value), AQA_MIN, AQA_MAX); aqaNum.value = state.aqa.toFixed(0); render(); }});
      aqaNum.addEventListener('input', function(){{ if(aqaNum.value==='') return; state.aqa = clamp(parseFloat(aqaNum.value), AQA_MIN, AQA_MAX); aqaSlider.value = state.aqa; render(); }});
      priceSlider.addEventListener('input', function(){{ state.price = clamp(parseFloat(priceSlider.value), PRICE_MIN, PRICE_MAX); priceNum.value = state.price.toFixed(2); render(); }});
      priceNum.addEventListener('input', function(){{ if(priceNum.value==='') return; state.price = clamp(parseFloat(priceNum.value), PRICE_MIN, PRICE_MAX); priceSlider.value = state.price; render(); }});

      document.querySelectorAll('.mini-btn[data-protocol]').forEach(function(btn){{
        btn.addEventListener('click', function(){{ state.protocol = parseFloat(btn.getAttribute('data-protocol')); protocolSlider.value = clamp(state.protocol,100,700); protocolNum.value = state.protocol.toFixed(1); render(); }});
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
               ps_explorer_html: str) -> str:
    now_beijing = datetime.now(timezone(timedelta(hours=8)))
    generated = now_beijing.strftime("%Y-%m-%d %H:%M")
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
      <span>Generated <strong>{generated} CST</strong></span>
      <span>Cadence <strong>12:00 Beijing</strong></span>
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
  </section>

  <section class="section">
    <div class="section-head">
      <span class="section-num">03</span>
      <h2 class="section-title">USDC Reserve-Income Estimate (AQA / AQAv2)</h2>
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
    <span class="footer-note">Auto-refreshed daily at 12:00 Beijing time.</span>
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
    usdc_estimate_html = build_usdc_estimate_html(live_float_usd)
    ps_explorer_html = build_ps_explorer_html(live_float_usd)

    html = build_html(title, body_html, chart_html, brief_path, len(df),
                       usdc_float_chart_html, usdc_estimate_html, ps_explorer_html)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
