"""
Composite risk scoring engine.

Five components, each 0-100 (higher = riskier):
  Liquidity (25%)   — TVL trend, drawdown from peak
  Market    (20%)   — token price volatility + concentration
  SC Risk   (25%)   — audit freshness, exploit history, bug bounty
  Governance(20%)   — token distribution, timelock, chain-specific flags
  Sentiment (10%)   — Fear & Greed + protocol news sentiment

Signals: INCREASE (<30) | HOLD (30-45) | REDUCE (45-65) | EXIT (>65)
"""
import math
import statistics
from datetime import datetime

import numpy as np

from config import PROTOCOLS, THRESHOLDS, WEIGHTS


# ── Component scorers ──────────────────────────────────────────────────────────

def _liquidity_score(tvl_series: list[dict], utilization: float | None = None) -> tuple[float, dict]:
    if not tvl_series:
        return 50.0, {"drawdown_pct": 0, "change_7d": 0, "change_30d": 0, "current_tvl": 0}

    vals = [e.get("totalLiquidityUSD", 0.0) for e in tvl_series]
    current = vals[-1]
    peak    = max(vals) if vals else current

    drawdown = (peak - current) / peak if peak > 0 else 0.0

    def pct_change(lookback):
        if len(vals) < lookback + 1:
            return 0.0
        ref = vals[-(lookback + 1)]
        return (current - ref) / ref if ref > 0 else 0.0

    ch7  = pct_change(7)
    ch30 = pct_change(30)

    # Each component bounded, then summed
    s_drawdown = min(drawdown * 55, 40)
    s_7d       = min(max(-ch7  * 150, 0), 30)
    s_30d      = min(max(-ch30 *  90, 0), 30)

    # Utilization penalty for lending protocols: >80% util is a risk signal
    s_util = 0.0
    if utilization is not None and utilization > 0.80:
        s_util = min((utilization - 0.80) * 100, 20)   # up to 20 pts over 80%
    score  = s_drawdown + s_7d + s_30d + s_util

    meta = {
        "drawdown_pct": round(drawdown * 100, 2),
        "change_7d":    round(ch7  * 100, 2),
        "change_30d":   round(ch30 * 100, 2),
        "current_tvl":   current,
        "peak_tvl":      peak,
        "utilization":   round(utilization * 100, 1) if utilization is not None else None,
    }
    return round(min(score, 100), 2), meta


def _market_score(price_history: list[float]) -> tuple[float, dict]:
    if len(price_history) < 5:
        return 45.0, {"volatility_30d": 0, "price_return_30d": 0}

    prices = np.array(price_history, dtype=float)
    rets   = np.diff(np.log(prices + 1e-9))

    daily_vol = float(np.std(rets))
    vol_score = float(min(daily_vol * 1_200, 60))

    p30_ret   = float((prices[-1] - prices[0]) / prices[0]) if prices[0] > 0 else 0.0
    ret_score = float(min(max(-p30_ret * 40, 0), 20))

    score = vol_score + ret_score
    return round(min(score, 100), 2), {
        "volatility_30d":   round(daily_vol * 100, 3),
        "price_return_30d": round(p30_ret * 100, 2),
    }


def _sc_score(meta: dict) -> float:
    age     = meta["audit_age_days"]
    exploit = meta["exploit_severity"]
    bounty  = meta["bug_bounty_usd"]

    # Audit freshness: 0-40 pts, linear up to 2 years
    s_audit = min(age / 730 * 40, 40)

    # Exploit history: 0, 20, 40
    s_exploit = exploit * 20

    # Missing or minimal bug bounty signals lack of security maturity
    if bounty == 0:
        s_bounty = 20
    elif bounty < 100_000:
        s_bounty = 15
    elif bounty < 500_000:
        s_bounty = 10
    elif bounty < 1_000_000:
        s_bounty = 5
    else:
        s_bounty = 0

    return round(min(s_audit + s_exploit + s_bounty, 100), 2)


def _governance_score(meta: dict, proposal_count: int = 0) -> float:
    gini  = meta["token_gini"]
    chain = meta["chain"]

    s_concentration = gini * 50
    s_timelock      = 0 if meta["has_timelock"] else 30

    # Chain-specific governance premiums
    if "TRON" in chain:
        s_chain = 20   # highly centralised, Justin Sun
    elif "Solana" in chain:
        s_chain = 12   # faster finality but less battle-tested governance
    elif "BNB" in chain:
        s_chain = 8
    else:
        s_chain = 0

    # Governance spike: many proposals in 30 days can signal instability
    s_spike = min(max(proposal_count - 5, 0) * 2, 15)

    return round(min(s_concentration + s_timelock + s_chain + s_spike, 100), 2)


def _sentiment_score(fng_value: int, news_polarity: float) -> float:
    # Fear & Greed: lower index = more fear = more risk
    # Invert so that "Extreme Fear" (10) → 45 pts, "Extreme Greed" (90) → 5 pts
    fng_score = round((1 - fng_value / 100) * 45, 2)

    # news_polarity in [-1, 1]; negative → more risk
    news_score = round((1 - (news_polarity + 1) / 2) * 55, 2)

    return round(min(fng_score + news_score * 0.1, 100), 2)  # news weighted lightly


# ── Signal logic ───────────────────────────────────────────────────────────────

def _signal(composite: float, anomaly_count: int = 0) -> str:
    # anomaly_count is recent (90-day) high/medium events only.
    # Cap contribution at 3 events × 3 pts = 9 pts max so a healthy
    # protocol with noisy TVL isn't pushed straight to EXIT.
    nudge = min(anomaly_count, 3) * 3
    score = composite + nudge
    if score < 30:
        return "INCREASE"
    elif score < 45:
        return "HOLD"
    elif score < 65:
        return "REDUCE"
    return "EXIT"


def _rationale(name: str, breakdown: dict, anomaly_count: int) -> str:
    flags = []
    if breakdown["smart_contract"] > 50:
        flags.append("aging audits or prior exploit")
    if breakdown["governance"] > 60:
        flags.append("concentrated token distribution")
    if breakdown["liquidity"] > 40:
        flags.append("significant TVL decline from peak")
    if breakdown["market"] > 55:
        flags.append("elevated token price volatility")
    if anomaly_count > 0:
        flags.append(f"{anomaly_count} on-chain anomaly signal(s) detected")

    if not flags:
        return "Healthy across all tracked dimensions. No elevated flags."
    return "Flagged: " + "; ".join(flags) + "."


# ── Main entry ─────────────────────────────────────────────────────────────────

def score_protocol(
    name: str,
    tvl_series:     list[dict],
    price_history:  list[float],
    fng_value:      int,
    news_sentiment: float,
    anomaly_count:  int = 0,
    utilization:    float | None = None,
    proposal_count: int = 0,
) -> dict:
    meta = PROTOCOLS[name]

    liq_score,  liq_meta  = _liquidity_score(tvl_series, utilization)
    mkt_score,  mkt_meta  = _market_score(price_history)
    sc_score              = _sc_score(meta)
    gov_score             = _governance_score(meta, proposal_count)
    sent_score            = _sentiment_score(fng_value, news_sentiment)

    w = WEIGHTS
    composite = (
        w["liquidity"]      * liq_score +
        w["market"]         * mkt_score +
        w["smart_contract"] * sc_score  +
        w["governance"]     * gov_score +
        w["sentiment"]      * sent_score
    )
    composite = round(composite, 2)

    breakdown = {
        "liquidity":     liq_score,
        "market":        mkt_score,
        "smart_contract":sc_score,
        "governance":    gov_score,
        "sentiment":     sent_score,
    }

    signal = _signal(composite, anomaly_count)

    return {
        "composite":       composite,
        "breakdown":       breakdown,
        "signal":          signal,
        "rationale":       _rationale(name, breakdown, anomaly_count),
        "category":        meta["category"],
        "chain":           meta["chain"],
        "token":           meta["token"],
        "current_tvl":     liq_meta.get("current_tvl", 0),
        "peak_tvl":        liq_meta.get("peak_tvl", 0),
        "drawdown_pct":    liq_meta.get("drawdown_pct", 0),
        "change_7d":       liq_meta.get("change_7d", 0),
        "change_30d":      liq_meta.get("change_30d", 0),
        "utilization":     liq_meta.get("utilization"),
        "proposal_count":  proposal_count,
        "volatility_30d":  mkt_meta.get("volatility_30d", 0),
        "price_return_30d":mkt_meta.get("price_return_30d", 0),
    }


def score_all(data: dict, anomaly_counts: dict | None = None) -> dict[str, dict]:
    fng_value      = data["fear_greed"].get("value", 50)
    anomaly_counts = anomaly_counts or {}
    utilization    = data.get("utilization", {})
    governance     = data.get("governance", {})
    results = {}
    for name in PROTOCOLS:
        results[name] = score_protocol(
            name           = name,
            tvl_series     = data["tvl"].get(name, []),
            price_history  = data["px_hist"].get(name, []),
            fng_value      = fng_value,
            news_sentiment = data["sentiment"].get(name, 0.0),
            anomaly_count  = anomaly_counts.get(name, 0),
            utilization    = utilization.get(name),
            proposal_count = governance.get(name, 0),
        )
    return results
