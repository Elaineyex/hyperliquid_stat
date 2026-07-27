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

ROOT = Path(__file__).resolve().parent
LOGS_DIR = ROOT / "logs"
DB_PATH = ROOT / "hyperliquid_stats.db"
OUTPUT_PATH = ROOT / "dashboard.html"

MD_EXTENSIONS = ["tables", "sane_lists"]

# --- AQA (Aligned Quote Asset) USDC reserve-income estimate (off-protocol, NOT in revenue_daily) ---
# Manual estimate, not a live feed. See logs/2026-07-24-coinbase-usdc-reserve-income-research.md
# and logs/2026-07-24-usdc-revenue-vs-user-yield-research.md for full sourcing/methodology and
# caveats before changing these numbers.
USDC_ESTIMATE = {
    "as_of": "2026-07-24",
    "float_usd": 6.176e9,         # Coinbase's own AQAv2 activation post (2026-06-08): USDC reserves
                                   # at activation, 95.06% of Hyperliquid L1 stablecoins
    "hl_share": 0.90,              # reported share of reserve income paid to Hyperliquid via AQA/AQAv2
    "yield_low": 0.030,
    "yield_base": 0.035,           # derived from Circle Q1'26 reserve income / avg circulating USDC
    "yield_high": 0.040,
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


def build_usdc_estimate_html() -> str:
    """Render the AQA (Aligned Quote Asset) USDC reserve-income estimate card.

    This is NOT on-chain protocol revenue and is NOT included in revenue_daily,
    revenue_7d_avg, or hype_ps_ratio anywhere else in this dashboard/DB — it's
    an off-chain interest-income split between Coinbase/Circle and Hyperliquid
    (the AQA/AQAv2 program), confirmed absent from ASXN's own rev-fee-breakdown
    taxonomy. It funds the Hyperliquid Assistance Fund's HYPE buybacks directly,
    separately from HLP/vault yield paid to individual USDC depositors — see the
    research log for why those are parallel, non-overlapping mechanisms. Manual
    estimate; no live data source exists for the underlying float or yield.
    See logs/2026-07-24-coinbase-usdc-reserve-income-research.md and
    logs/2026-07-24-usdc-revenue-vs-user-yield-research.md.
    """
    e = USDC_ESTIMATE
    rows = []
    for label, y in (("Low", e["yield_low"]), ("Base", e["yield_base"]), ("High", e["yield_high"])):
        annual = e["float_usd"] * y * e["hl_share"]
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
      Hyperliquid (Coinbase keeps the remaining ~10%). Per Coinbase's own AQAv2 activation
      announcement (2026-06-08), USDC reserves stood at <strong>${e['float_usd']/1e9:.2f}B</strong>
      when yield began flowing &mdash; &asymp;8% of USDC's global circulating supply at the time,
      and 95.06% of Hyperliquid L1's own stablecoin base. This income is routed to the
      <strong>Hyperliquid Assistance Fund</strong>, which executes open-market
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
      with the Fed funds target range at the time (3.50&ndash;3.75%). The AQA/AQAv2 program, its
      90% share, and Assistance-Fund routing are corroborated across multiple secondary outlets
      (CoinDesk, CryptoBriefing, Bankless) plus Coinbase's own activation post &mdash; stronger than
      the single-JPMorgan-source framing this estimate started from &mdash; but no primary
      Hyperliquid governance-forum document has been located (unlike Circle&ndash;Coinbase's
      SEC-filed Collaboration Agreement, which confirms the analogous split there is a recurring
      monthly payment, not a one-off). Sources disagree on the accrual timeline (Coinbase's post
      says yield started 2026-06-08; other reporting cites an Aug 26 accrual start / Oct 3 first
      Assistance Fund payment) &mdash; unresolved, see research log. Confirmed via ASXN's own
      compiled JS that this income has no path into Hyperliquid's on-chain fee revenue at all.
      As of {e['as_of']}.</p>
    </div>
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
"""


def build_html(title: str, body_html: str, chart_html: str, brief_path: Path,
               row_count: int, usdc_estimate_html: str) -> str:
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
    {usdc_estimate_html}
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
    usdc_estimate_html = build_usdc_estimate_html()
    html = build_html(title, body_html, chart_html, brief_path, len(df), usdc_estimate_html)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard written: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
