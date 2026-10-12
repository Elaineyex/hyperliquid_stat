"""AQAv2 (Aligned Quote Asset) USDC reserve-income payouts, read from the Hyperliquid API.

Mechanism (hyperliquid.gitbook.io/hyperliquid-docs/hypercore/aligned-quote-assets): accrued
daily at 0 UTC on the USDC float, settled in 30-day intervals, and paid to the Assistance Fund
8 days after each interval closes. On-chain the payout shows up as a zero-hash internal `send`
of USDC from the system address 0x5000...0000 to the Assistance Fund (first one 2026-10-04,
$14.58M for the 2026-08-26..09-25 interval) -- see logs/2026-10-12-aqav2-first-payout.md.

This income is NOT in DefiLlama's dailyRevenue (so not in revenue_daily). It is added on top
of on-chain revenue for the "incl. AQA" P/S.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

import requests

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
ASSISTANCE_FUND_ADDR = "0xfefefefefefefefefefefefefefefefefefefefe"
AQA_PAYOUT_SENDER = "0x5000000000000000000000000000000000000000"
AQA_MIN_PAYOUT_USD = 1_000.0  # filters out test/dust sends like the 2 USDC one on 2026-10-03
AQA_ACCRUAL_START = date(2026, 8, 26)
AQA_INTERVAL_DAYS = 30
AQA_SETTLE_DAYS = 8
# Ledger scan starts a few days before the first possible payout date.
_SCAN_START = datetime(2026, 9, 25, tzinfo=timezone.utc)


def fetch_aqa_payouts() -> list[dict] | None:
    """Return AQAv2 payouts to the Assistance Fund, oldest first, or None if the fetch failed.

    Each payout: {"paid_at": datetime (UTC), "paid_date": date, "amount_usd": float,
    "interval_start": date, "interval_end": date (exclusive), "annualized_usd": float}.
    Interval k is assigned by order: [accrual_start + 30k, accrual_start + 30(k+1)).
    """
    start_ms = int(_SCAN_START.timestamp() * 1000)
    seen = set()
    entries = []
    try:
        for _ in range(100):  # the endpoint pages by count; walk forward until exhausted
            resp = requests.post(HL_INFO_URL, json={
                "type": "userNonFundingLedgerUpdates",
                "user": ASSISTANCE_FUND_ADDR,
                "startTime": start_ms,
            }, timeout=20)
            resp.raise_for_status()
            page = resp.json()
            new = [x for x in page if (x["time"], x["hash"], str(x["delta"])) not in seen]
            if not new:
                break
            for x in new:
                seen.add((x["time"], x["hash"], str(x["delta"])))
            entries.extend(new)
            start_ms = max(x["time"] for x in page) + 1
    except Exception as exc:
        print(f"AQA payout fetch failed: {exc}", file=sys.stderr)
        return None

    payouts = []
    for x in sorted(entries, key=lambda x: x["time"]):
        d = x["delta"]
        if (d.get("type") == "send" and d.get("user", "").lower() == AQA_PAYOUT_SENDER
                and d.get("token") == "USDC" and float(d.get("amount", 0)) >= AQA_MIN_PAYOUT_USD):
            paid_at = datetime.fromtimestamp(x["time"] / 1000, timezone.utc)
            payouts.append({"paid_at": paid_at, "paid_date": paid_at.date(),
                            "amount_usd": float(d["amount"])})
    for k, p in enumerate(payouts):
        p["interval_start"] = AQA_ACCRUAL_START + timedelta(days=AQA_INTERVAL_DAYS * k)
        p["interval_end"] = p["interval_start"] + timedelta(days=AQA_INTERVAL_DAYS)
        p["annualized_usd"] = p["amount_usd"] * 365 / AQA_INTERVAL_DAYS
    return payouts


def aqa_annualized_as_of(payouts: list[dict] | None, as_of: date) -> float | None:
    """Annualized AQAv2 revenue known on `as_of`: latest payout paid on or before that day
    x 365/30. 0.0 before the first payout (nothing had been paid yet -- no look-ahead);
    None if payouts couldn't be fetched."""
    if payouts is None:
        return None
    known = [p for p in payouts if p["paid_date"] <= as_of]
    return known[-1]["annualized_usd"] if known else 0.0
