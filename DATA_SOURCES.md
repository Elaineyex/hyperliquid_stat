# Hyperliquid Data Source Reference

What we can fetch from where, what's actually wired into this repo vs. browser-only/manual, and known access blockers. Compiled from `plot_macro_trend.py`, `generate_revenue_breakdown.py`, `CLAUDE.md`, and research logs in `logs/` (gitignored — see `2026-07-01-per-market-revenue-api-research.md` and `2026-07-24-coinbase-usdc-reserve-income-research.md` for the underlying investigations). Last updated 2026-07-24 — re-verify access/status before relying on the "blocked"/"403" rows if it's been a while.

## In active use in this repo

| Source | URL / endpoint | What it gives us | Used by | Access |
| :--- | :--- | :--- | :--- | :--- |
| **DefiLlama** | `api.llama.fi/overview/fees/hyperliquid?dataType=dailyRevenue` | Daily net protocol revenue, 3 top-level buckets: `Hyperliquid Perps`, `Hyperliquid Spot Orderbook`, `Hyperliquid HLP` (+ ~200 ecosystem-app sources in the detailed breakdown) | `plot_macro_trend.py`, `generate_revenue_breakdown.py` → `revenue_daily` in DB | Public, no auth, reliable |
| **DefiLlama (Spectra V2)** | `api.llama.fi/summary/fees/spectra-v2?dataType=dailyRevenue` | Small deduction subtracted from gross to get net protocol revenue | `plot_macro_trend.py` | Public |
| **Hyperliquid `/info` API** | `api.hyperliquid.xyz/info` (POST) | `metaAndAssetCtxs` (live price/OI/funding/`dayNtlVlm` per market), `perpDexs` (HIP-3 builder metadata, `deployerFeeScale`), `candleSnapshot` (historical OHLCV per coin), `globalStats` (aggregate volume/users) | `generate_revenue_breakdown.py` (volume context, HIP-3 builder table) | Public, no auth |
| **CoinGecko** | `api.coingecko.com/api/v3/coins/hyperliquid` and `.../market_chart` | HYPE spot price, circulating/total supply, market cap, 220-day price history (used for BTC too) | `plot_macro_trend.py` → `hype_price`, `btc_price`, `hype_circulating_supply`, `hype_market_cap` in DB | Public, rate-limited (script caches to `CACHE_DIR`) |

## Known, browser-only or manually cross-referenced (not wired into any script)

| Source | URL | What it has | Why it's not automated | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **ASXN Hyperscreener** | `hyperscreener.asxn.xyz/home`, `/rev-fee-breakdown`, `/staking`, `/portfolio` | Revenue by category with native/HIP-3 split, builder-code revenue and user counts, vault screener (22 metrics), staking/validator data, spot HIP-1 market overview | Client-rendered React SPA — `WebFetch` returns only the empty shell, no content in raw HTML | Underlying API (`api-hyperliquid.asxn.xyz/api`, incl. `/income-statement`, `/buyback/revenue-metrics`) is **blocked by Cloudflare Turnstile** (verified 2026-07-01). This is the source of the 93.1%/6.9% native/HIP-3 split benchmark and the ASXN category-taxonomy audit used to confirm USDC reserve income has no path into on-chain revenue — both obtained by manually reading the site / its compiled JS, not by API call |
| **HypurrScan** | `hypurrscan.io/stats` and other explorer pages | HIP-2 USDC TVL (order-book liquidity), Spot USDC TVL chart, auction-fee chart, Dutch-auction/TWAP/token-deploy tracking, wallet fund-flow tracking | Same problem — client-rendered SPA, `WebFetch` gets no content | No documented public API found. Explorer-style tool (think Etherscan for Hyperliquid L1), not a revenue/fee-breakdown source — useful for TVL/liquidity/whale-flow questions, not for protocol revenue |
| **Hyperliquid stats CDN** | `stats-data.hyperliquid.xyz/Mainnet/daily_usd_volume_by_coin` | Per-coin daily USD volume (would be useful for per-market analysis) | **403 Forbidden** — S3 bucket ACL restricted, no public access (verified 2026-07-01) | Would still only be volume, not fee revenue, even if accessible |
| **Circle transparency reports / 10-Q filings** | investors.circle.com, SEC EDGAR | Circle's quarterly reserve income, average circulating USDC — used as a yield proxy (Q1'26: $653M / ~$76.15B ≈ 3.4% annualized) | Manual — no API; pulled from PDF/filing text | Cross-project source, also used in the `stock_eval` CRCL deep-dive |
| **SEC EDGAR (Circle–Coinbase Collaboration Agreement)** | CIK 1876042, Exhibit 10.1 | Primary contract text for the Circle↔Coinbase USDC revenue split (percentages redacted, mechanism confirmed) | Manual document read, not an API | The one *primary* document in this whole chain; no equivalent exists yet for Coinbase↔Hyperliquid |
| **Crypto news outlets** (CoinDesk, CryptoBriefing, Bankless, JPMorgan research via secondary reporting) | various | AQA/AQAv2 program details, $6.176B USDC-on-Hyperliquid float, 90% share, Assistance Fund routing | Secondary reporting, no primary Hyperliquid governance-forum document located | See `2026-07-24-coinbase-usdc-reserve-income-research.md` and `2026-07-24-usdc-revenue-vs-user-yield-research.md` for full sourcing and caveats |

## Explicitly NOT available anywhere (public or private)

| Data | Status |
| :--- | :--- |
| Per-market protocol fee revenue (e.g. "BTC perp generated $X today") | Not exposed by any public source. ASXN computes it internally from raw L1 tx data (node access or privileged feed), not reproducible externally. Best public proxy: two-rate volume-share model, see `2026-07-01-per-market-revenue-api-research.md` |
| HIP-3 deployer's own cut of fees (xyz take vs. Hyperliquid take, per market) | Not exposed; only `deployerFeeScale` (a multiplier, not a dollar figure) is public via `perpDexs` |
| Live Hyperliquid Foundation/Labs treasury balance or USDC reserve-income receipts | No public treasury disclosure exists. AQA/AQAv2 figures are all estimated from secondary reporting |
| Historical (non-today) per-coin `dayNtlVlm` | The live `metaAndAssetCtxs` field is a rolling 24h figure for *today* only — use `candleSnapshot` for historical per-coin volume instead |

## Quick picks by question type

| If you need... | Go to |
| :--- | :--- |
| Daily net protocol revenue (what this repo tracks) | DefiLlama `dailyRevenue` |
| Today's live market/volume/funding snapshot | Hyperliquid `/info` `metaAndAssetCtxs` |
| Historical per-coin volume | Hyperliquid `/info` `candleSnapshot` |
| HIP-3 builder dex list + fee scale | Hyperliquid `/info` `perpDexs` |
| Revenue *by category* with native/HIP-3 split, builder-code stats | ASXN Hyperscreener (browser only, no API) |
| Spot/HIP-2 order-book TVL, on-chain fund flows, auctions | HypurrScan (browser only, no API) |
| USDC reserve-income / AQA figures | Secondary crypto-news reporting + Coinbase's own announcement post — no live feed, treat as estimate |
| HYPE/BTC price, supply | CoinGecko |
