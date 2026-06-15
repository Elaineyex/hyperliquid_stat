#!/bin/bash

set -euo pipefail

# Daily Hyperliquid Report Runner
# This script activates the virtual environment, runs the analysis, and generates a markdown report.

cd /Users/elaineye/agent/hyperliquid_stats
source .venv/bin/activate

mkdir -p .cache/matplotlib logs
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export XDG_CACHE_HOME="$PWD/.cache"

TODAY=${1:-$(date -u +%Y-%m-%d)}
LOG_FILE="logs/${TODAY}.md"

echo "Running daily report for ${TODAY}..."
if ! OUTPUT=$(python plot_macro_trend.py "$TODAY" 2>&1); then
  printf '%s\n' "$OUTPUT" >&2
  exit 1
fi

HYPE_LINE=$(printf '%s\n' "$OUTPUT" | grep "HYPE Price:" || true)
BTC_LINE=$(printf '%s\n' "$OUTPUT" | grep "BTC Price:" || true)
REV_LINE=$(printf '%s\n' "$OUTPUT" | grep "Daily Revenue:" || true)
REV_7D=$(printf '%s\n' "$OUTPUT" | grep "7d avg:" || true)
REV_30D=$(printf '%s\n' "$OUTPUT" | grep "30d avg:" || true)
VAL_LINE=$(printf '%s\n' "$OUTPUT" | grep "HYPE Valuation:" || true)
MARKET_CAP_LINE=$(printf '%s\n' "$OUTPUT" | grep "Market Cap:" || true)
PS_LINE=$(printf '%s\n' "$OUTPUT" | grep "P/S 7d ann:" || true)

HYPE_PRICE=$(printf '%s\n' "$HYPE_LINE" | grep -oE '\$[0-9]+\.[0-9]+' | head -1 || true)
HYPE_1D=$(printf '%s\n' "$HYPE_LINE" | grep -oE '[+-][0-9]+\.[0-9]+% 1d' | sed 's/ 1d//' || true)
HYPE_7D=$(printf '%s\n' "$HYPE_LINE" | grep -oE '[+-][0-9]+\.[0-9]+% 7d' | sed 's/ 7d//' || true)
HYPE_30D=$(printf '%s\n' "$HYPE_LINE" | grep -oE '[+-][0-9]+\.[0-9]+% 30d' | sed 's/ 30d//' || true)

BTC_PRICE=$(printf '%s\n' "$BTC_LINE" | grep -oE '\$[0-9,]+' | head -1 || true)
BTC_1D=$(printf '%s\n' "$BTC_LINE" | grep -oE '[+-][0-9]+\.[0-9]+% 1d' | sed 's/ 1d//' || true)
BTC_7D=$(printf '%s\n' "$BTC_LINE" | grep -oE '[+-][0-9]+\.[0-9]+% 7d' | sed 's/ 7d//' || true)
BTC_30D=$(printf '%s\n' "$BTC_LINE" | grep -oE '[+-][0-9]+\.[0-9]+% 30d' | sed 's/ 30d//' || true)

REV_TODAY=$(printf '%s\n' "$REV_LINE" | grep -oE '\$[0-9,]+' | head -1 || true)
REV_DOD=$(printf '%s\n' "$REV_LINE" | grep -oE '[+-][0-9]+\.[0-9]+% vs prev day' | sed 's/ vs prev day//' || true)
REV_7D_AVG=$(printf '%s\n' "$REV_7D" | grep -oE '\$[0-9,]+' | head -1 || true)
REV_30D_AVG=$(printf '%s\n' "$REV_30D" | grep -oE '\$[0-9,]+' | head -1 || true)
REV_7D_VS_30D=$(printf '%s\n' "$REV_30D" | grep -oE '[+-][0-9]+\.[0-9]+%' | tail -1 || true)
CIRC_PCT=$(printf '%s\n' "$VAL_LINE" | grep -oE '[0-9]+\.[0-9]+% of' | sed 's/ of//' || true)
TOTAL_SUPPLY=$(printf '%s\n' "$VAL_LINE" | grep -oE 'of [0-9,]+ supply' | sed 's/of //; s/ supply//' || true)
HYPE_MARKET_CAP=$(printf '%s\n' "$MARKET_CAP_LINE" | grep -oE '\$[0-9,]+' | head -1 || true)
HYPE_PS=$(printf '%s\n' "$PS_LINE" | grep -oE '[0-9]+\.[0-9]+x' | head -1 || true)

REQUIRED_VARS=(
  HYPE_PRICE HYPE_1D HYPE_7D HYPE_30D
  BTC_PRICE BTC_1D BTC_7D BTC_30D
  REV_TODAY REV_7D_AVG REV_30D_AVG REV_7D_VS_30D
  CIRC_PCT TOTAL_SUPPLY HYPE_MARKET_CAP HYPE_PS
)

for var_name in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var_name}" ]]; then
    echo "Failed to parse required field: ${var_name}" >&2
    printf '%s\n' "$OUTPUT" >&2
    exit 1
  fi
done

export TODAY LOG_FILE
export HYPE_PRICE HYPE_1D HYPE_7D HYPE_30D
export BTC_PRICE BTC_1D BTC_7D BTC_30D
export REV_TODAY REV_DOD REV_7D_AVG REV_30D_AVG REV_7D_VS_30D
export CIRC_PCT TOTAL_SUPPLY HYPE_MARKET_CAP HYPE_PS

python - <<'PY'
import math
import os


def parse_money(value: str) -> float:
    return float(value.replace("$", "").replace(",", ""))


def parse_pct(value: str) -> float:
    return float(value.replace("%", ""))


def fmt_pp(value: float) -> str:
    return f"{value:+.1f}pp"


def fmt_pct(value: float) -> str:
    return f"{value:+.1f}%"


def round_half(value: float, direction: str) -> float:
    scaled = value * 2
    if direction == "down":
        return math.floor(scaled) / 2
    return math.ceil(scaled) / 2


def fmt_level(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def fmt_compact_money(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if abs_value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,.0f}"


today = os.environ["TODAY"]
log_file = os.environ["LOG_FILE"]

hype_price_raw = os.environ["HYPE_PRICE"]
hype_1d_raw = os.environ["HYPE_1D"]
hype_7d_raw = os.environ["HYPE_7D"]
hype_30d_raw = os.environ["HYPE_30D"]
btc_price_raw = os.environ["BTC_PRICE"]
btc_1d_raw = os.environ["BTC_1D"]
btc_7d_raw = os.environ["BTC_7D"]
btc_30d_raw = os.environ["BTC_30D"]
rev_today_raw = os.environ["REV_TODAY"]
rev_dod_raw = os.environ.get("REV_DOD", "")
rev_7d_raw = os.environ["REV_7D_AVG"]
rev_30d_raw = os.environ["REV_30D_AVG"]
rev_gap_raw = os.environ["REV_7D_VS_30D"]
circ_pct_raw = os.environ["CIRC_PCT"]
total_supply_raw = os.environ["TOTAL_SUPPLY"]
hype_market_cap_raw = os.environ["HYPE_MARKET_CAP"]
hype_ps_raw = os.environ["HYPE_PS"]
hype_market_cap_display = fmt_compact_money(parse_money(hype_market_cap_raw))

hype_price = parse_money(hype_price_raw)
hype_1d = parse_pct(hype_1d_raw)
hype_7d = parse_pct(hype_7d_raw)
hype_30d = parse_pct(hype_30d_raw)
btc_1d = parse_pct(btc_1d_raw)
btc_7d = parse_pct(btc_7d_raw)
btc_30d = parse_pct(btc_30d_raw)
rev_today = parse_money(rev_today_raw)
rev_7d = parse_money(rev_7d_raw)
rev_30d = parse_money(rev_30d_raw)
rev_gap = parse_pct(rev_gap_raw)
rev_dod = parse_pct(rev_dod_raw) if rev_dod_raw else None
rel_gap = hype_7d - btc_7d

support_low = round_half(hype_price * 0.95, "down")
support_high = round_half(hype_price * 0.98, "down")
res_low = round_half(hype_price * 1.04, "up")
res_high = round_half(hype_price * 1.08, "up")
stop = round_half(hype_price * 0.90, "down")

support_zone = f"${fmt_level(support_low)}-{fmt_level(support_high)}"
resistance_zone = f"${fmt_level(res_low)}-{fmt_level(res_high)}"
stop_level = f"${fmt_level(stop)}"

if btc_7d >= 5:
    if btc_30d >= 5:
        market_regime = (
            f"Risk-on macro. BTC is in a clear uptrend, up {btc_7d_raw} over 7d and holding firmly at "
            f"{btc_price_raw}, with a strong 30d return of {btc_30d_raw}. Broader crypto sentiment remains constructive."
        )
    else:
        market_regime = (
            f"Risk-on macro. BTC is recovering, up {btc_7d_raw} over 7d and reclaiming key levels near {btc_price_raw}. "
            f"The 30d return has improved to {btc_30d_raw}, suggesting macro conditions are stabilizing."
        )
elif btc_7d >= 1 and btc_30d > 0:
    if btc_1d < 0:
        market_regime = (
            f"Short-term consolidation inside a broader uptrend. BTC is easing {btc_1d_raw} on the day but still up "
            f"{btc_7d_raw} over 7d and {btc_30d_raw} over 30d. Macro conditions remain supportive, though momentum has cooled."
        )
    else:
        market_regime = (
            f"Constructive macro backdrop. BTC is grinding higher, up {btc_7d_raw} over 7d and {btc_30d_raw} over 30d, "
            f"while holding around {btc_price_raw}. The broader market remains firm but not euphoric."
        )
elif abs(btc_7d) < 1.5 and btc_30d >= 5:
    if btc_1d < 0:
        market_regime = (
            f"Short-term consolidation inside a broader uptrend. BTC is easing {btc_1d_raw} on the day and nearly flat on a 7d basis "
            f"({btc_7d_raw}), but the 30d return remains strong at {btc_30d_raw}. The market is digesting gains rather than breaking trend."
        )
    else:
        market_regime = (
            f"Mild risk-on consolidation. BTC is near flat on the week at {btc_7d_raw} but still up {btc_30d_raw} over 30d, "
            f"keeping the broader macro backdrop constructive around {btc_price_raw}."
        )
elif btc_7d <= -5:
    market_regime = (
        f"Risk-off macro. BTC is in a clear downtrend, down {btc_7d_raw} over 7d and struggling to hold {btc_price_raw}. "
        f"The 30d return at {btc_30d_raw} points to a softer broader market backdrop."
    )
elif btc_7d < 0:
    if btc_30d > 0:
        market_regime = (
            f"Mild risk-off. BTC is consolidating after a strong month, down {btc_7d_raw} over 7d but still up {btc_30d_raw} "
            f"over 30d. The market is digesting recent gains rather than breaking trend."
        )
    else:
        market_regime = (
            f"Choppy macro consolidation. BTC is mixed, down {btc_7d_raw} over 7d and {btc_30d_raw} over 30d, with sentiment "
            f"still fragile near {btc_price_raw}."
        )
else:
    market_regime = (
        f"Sideways macro consolidation. BTC is largely range-bound, with a {btc_7d_raw} 7d return and {btc_30d_raw} over 30d. "
        f"The broader market is waiting for a clearer directional catalyst."
    )

if rel_gap >= 10:
    relative_strength = (
        f"HYPE is materially outperforming BTC, up {hype_7d_raw} over 7d versus BTC {btc_7d_raw}, a {fmt_pp(rel_gap)} spread. "
        f"Price at {hype_price_raw} shows strong protocol-specific demand even against the macro tape."
    )
elif rel_gap >= 3:
    relative_strength = (
        f"HYPE continues to show relative strength, up {hype_7d_raw} over 7d versus BTC {btc_7d_raw}, a {fmt_pp(rel_gap)} outperformance. "
        f"The token is holding {hype_price_raw}, which suggests buyers are still supporting the trend."
    )
elif rel_gap >= 0:
    relative_strength = (
        f"HYPE is roughly keeping pace with BTC, posting {hype_7d_raw} over 7d versus BTC {btc_7d_raw}. "
        f"The relative trend is stable, though the move is not yet decisive."
    )
elif rel_gap <= -8:
    relative_strength = (
        f"HYPE is underperforming BTC in the short term, at {hype_7d_raw} over 7d versus BTC {btc_7d_raw}, a {fmt_pp(rel_gap)} gap. "
        f"Price around {hype_price_raw} suggests rotation into majors while HYPE digests prior gains."
    )
elif rel_gap <= -3:
    relative_strength = (
        f"HYPE is showing short-term weakness, at {hype_7d_raw} over 7d versus BTC {btc_7d_raw}, a {fmt_pp(rel_gap)} underperformance. "
        f"The 30d return of {hype_30d_raw} still points to a broader base, but near-term momentum has softened."
    )
else:
    relative_strength = (
        f"HYPE is modestly lagging BTC, at {hype_7d_raw} over 7d versus BTC {btc_7d_raw}. "
        f"The move looks more like consolidation than a structural breakdown for now."
    )

if rev_gap >= 8:
    if rev_dod is not None and rev_dod >= 10:
        revenue_signal = (
            f"Protocol revenue surged to {rev_today_raw} today ({fmt_pct(rev_dod)} versus the prior day), with the 7d avg at "
            f"{rev_7d_raw} running {rev_gap_raw} above the 30d avg at {rev_30d_raw}. Revenue acceleration remains intact."
        )
    else:
        revenue_signal = (
            f"Protocol revenue remains strong at {rev_today_raw} today, while the 7d avg at {rev_7d_raw} is still {rev_gap_raw} above "
            f"the 30d avg at {rev_30d_raw}. Network activity continues to trend constructively."
        )
elif rev_gap >= 3:
    revenue_signal = (
        f"Protocol revenue printed {rev_today_raw} today, with the 7d avg at {rev_7d_raw} running {rev_gap_raw} above the 30d avg at "
        f"{rev_30d_raw}. Fundamentals remain healthy even if price momentum has become more selective."
    )
elif rev_gap > -3:
    if rev_today >= rev_30d:
        revenue_signal = (
            f"Protocol revenue printed a solid {rev_today_raw} today. The 7d avg at {rev_7d_raw} is nearly in line with the 30d avg at "
            f"{rev_30d_raw} ({rev_gap_raw}), suggesting revenue momentum is stable."
        )
    else:
        revenue_signal = (
            f"Protocol revenue came in at {rev_today_raw} today, and the 7d avg at {rev_7d_raw} is close to the 30d avg at "
            f"{rev_30d_raw} ({rev_gap_raw}). Fundamentals look steady but not yet re-accelerating."
        )
elif rev_gap <= -10:
    revenue_signal = (
        f"Protocol revenue cooled to {rev_today_raw} today, with the 7d avg at {rev_7d_raw} now {rev_gap_raw} below the 30d avg at "
        f"{rev_30d_raw}. That points to a meaningful slowdown in network activity versus the prior month."
    )
else:
    revenue_signal = (
        f"Protocol revenue printed {rev_today_raw} today, though the 7d avg at {rev_7d_raw} is still {rev_gap_raw} below the 30d avg "
        f"at {rev_30d_raw}. The strong daily print may be an early sign of stabilization."
    )

if rel_gap >= 5 and rev_gap >= 5 and btc_7d >= 0:
    strategy = (
        f"Bullish bias. HYPE has both relative strength and revenue support. Look to add on pullbacks into the {support_zone} support zone; "
        f"next resistance sits around {resistance_zone}, with risk managed below {stop_level}."
    )
elif rel_gap >= 5 and btc_7d < 0:
    strategy = (
        f"Cautious accumulation. HYPE is outperforming a weak macro tape, which is constructive, but BTC still argues for sizing discipline. "
        f"Add selectively near {support_zone}; next resistance is {resistance_zone}, stop below {stop_level}."
    )
elif rel_gap >= 0 and rev_gap >= 0:
    strategy = (
        f"Hold with a bullish bias. The setup is constructive, but not yet a clean breakout. Favor entries on dips toward {support_zone}; "
        f"next resistance is {resistance_zone}, stop below {stop_level}."
    )
elif rev_gap >= 5:
    strategy = (
        f"Accumulate on weakness. HYPE is lagging BTC on price, but revenue trends remain constructive. Let price prove support around "
        f"{support_zone}, then lean in if relative strength starts to improve. Resistance is {resistance_zone}, stop below {stop_level}."
    )
elif rel_gap <= -5 and (hype_1d <= -5 or rev_today < rev_7d * 0.8):
    strategy = (
        f"Caution warranted. Price momentum and near-term participation both need to stabilize before adding. Wait for stronger support around "
        f"{support_zone} or a reclaim of relative strength; keep risk tight below {stop_level}."
    )
else:
    strategy = (
        f"Neutral / consolidation. The signal set is mixed, so patience makes sense here. Watch whether HYPE can base around {support_zone}; "
        f"a cleaner bullish case opens on a move back through {resistance_zone}, with risk below {stop_level}."
    )

report = f"""# $HYPE Morning Brief - {today}

**Price Action**
| Asset | Current | 1d Chg | 7d Chg | 30d Chg |
| :--- | :--- | :--- | :--- | :--- |
| **$BTC** | {btc_price_raw} | {btc_1d_raw} | {btc_7d_raw} | {btc_30d_raw} |
| **$HYPE** | {hype_price_raw} | {hype_1d_raw} | {hype_7d_raw} | {hype_30d_raw} |

**Protocol Revenue**
| Metric | Value |
| :--- | :--- |
| Today | {rev_today_raw} |
| 7d avg | {rev_7d_raw} |
| 30d avg | {rev_30d_raw} |
| 7d vs 30d | {rev_gap_raw} |

**Valuation**
| Metric | Value |
| :--- | :--- |
| Circulating supply | {circ_pct_raw} of {total_supply_raw} |
| Market cap | {hype_market_cap_display} |
| P/S, 7d revenue annualized | {hype_ps_raw} |

**Investment Summary**
- **Market Regime:** {market_regime}
- **Relative Strength:** {relative_strength}
- **Revenue Signal:** {revenue_signal}
- **Strategy:** {strategy}

> Data analysis only, not financial advice.
"""

with open(log_file, "w", encoding="utf-8") as handle:
    handle.write(report)
PY

echo "Report generated: ${LOG_FILE}"
echo "Chart saved: hyperliquid_6m_macro_trend.png"

if ! python generate_dashboard.py "$TODAY" 2>&1; then
  echo "Dashboard generation failed" >&2
  exit 1
fi
