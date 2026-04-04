"""
Five stress scenarios that simulate market shocks and estimate
per-protocol TVL impact + risk score deterioration.

Scenarios
─────────
  flash_crash      — Any protocol loses N% TVL within 24–48h (governance attack,
                     whale exit, exploit rumour, oracle failure). Contagion spreads
                     to correlated protocols based on shared collateral/pool exposure.
  btc_crash        — BTC price drops N%, dragging ETH via correlation + triggering
                     market-wide fear and liquidation cascades in collateral-heavy protocols
  eth_crash        — ETH price drops N%, triggers liquidation cascades
  tvl_exodus       — Mass withdrawal of M% of TVL across DeFi
  stablecoin_depeg — Major stablecoin loses P% of its peg
  exploit          — Simulated smart contract drain on a target protocol

Non-linear cascade: shocks above 20% trigger an amplification multiplier
that models the cliff-effect of mass liquidations hitting simultaneously.
Flash crash uses a speed multiplier on top of cascade — same loss over 24h
is far more dangerous than over 30 days because governance cannot respond.
"""
from config import (
    ETH_COLLATERAL_HEAVY,
    PROTOCOLS,
    STABLECOIN_EXPOSED,
    THRESHOLDS,
)

# BTC→ETH price correlation (30-day rolling average, historically ~0.82–0.88)
_BTC_ETH_CORRELATION = 0.85

# Protocols with direct or indirect BTC collateral exposure
_BTC_EXPOSED = {
    "Aave", "Compound", "Sky (MakerDAO)", "Lido",
    "Instadapp", "GMX", "Synthetix",
}

SCENARIOS = {
    "flash_crash": {
        "label":        "Protocol Flash Crash",
        "description":  "A protocol loses the specified TVL share within 24 hours. Models contagion to correlated protocols before governance can respond.",
        "param_label":  "TVL drop (%)",
        "param_range":  (10, 95),
        "param_default": 40,
    },
    "btc_crash": {
        "label":        "BTC Market Crash",
        "description":  "Sharp BTC decline propagates to ETH collateral via high correlation, driving TVL outflows and liquidation cascades in lending protocols.",
        "param_label":  "BTC price drop (%)",
        "param_range":  (10, 70),
        "param_default": 30,
    },
    "eth_crash": {
        "label":       "ETH Price Crash",
        "description": "ETH price decline triggers liquidation cascades across lending and staking protocols with ETH collateral exposure.",
        "param_label": "ETH price drop (%)",
        "param_range": (10, 70),
        "param_default": 40,
    },
    "tvl_exodus": {
        "label":       "DeFi Liquidity Exodus",
        "description": "Coordinated TVL withdrawals across DeFi, driven by macro risk-off sentiment or broad loss of confidence.",
        "param_label": "TVL outflow (%)",
        "param_range": (5, 60),
        "param_default": 30,
    },
    "stablecoin_depeg": {
        "label":       "Stablecoin Depeg",
        "description": "A major stablecoin trades below peg, causing pool imbalances and collateral devaluation in exposed protocols.",
        "param_label": "Depeg magnitude (%)",
        "param_range": (1, 25),
        "param_default": 8,
    },
    "exploit": {
        "label":       "Smart Contract Exploit",
        "description": "Targeted exploit drains a protocol's TVL, with second-order impact on closely correlated protocols.",
        "param_label": "TVL drained (%)",
        "param_range": (10, 90),
        "param_default": 60,
    },
}

# Correlation pairs (protocol → protocols it pulls down if it fails)
_CONTAGION = {
    "Curve Finance":  ["Convex Finance", "Frax Finance", "Yearn Finance"],
    "Aave":           ["Instadapp", "Compound"],
    "Lido":           ["Curve Finance", "Frax Finance"],
    "Sky (MakerDAO)": ["Aave", "Compound", "Frax Finance"],
    "Compound":       ["Aave"],
}


def _cascade_multiplier(param: float) -> float:
    """Non-linear amplification above 20% shock.
    Below 20%: orderly deleveraging. Above 20%: liquidations cluster,
    utilization spikes, and protocols approach insolvency cliffs simultaneously.
    Based on empirical TVL drawdowns during March 2020 and May 2021 crashes."""
    if param <= 20:
        return 1.0
    # Each 10% above the 20% threshold adds ~15% more impact
    extra = (param - 20) / 10
    return round(1.0 + extra * 0.15, 3)


def _tvl_impact(name: str, scenario: str, param: float) -> float:
    """Estimated % TVL change for a protocol under a scenario."""
    meta    = PROTOCOLS[name]
    cascade = _cascade_multiplier(param)

    if scenario == "flash_crash":
        # Handled entirely in run_scenario (target-specific, like exploit)
        return 0.0

    if scenario == "btc_crash":
        # BTC drops param% → ETH drops param * correlation %
        eth_equiv = param * _BTC_ETH_CORRELATION

        # Market-wide fear drives universal outflows regardless of BTC exposure
        base_fear = param * 0.12   # even non-ETH protocols see withdrawals

        if name in _BTC_EXPOSED or name in ETH_COLLATERAL_HEAVY:
            # Direct collateral pressure from ETH re-pricing
            base = eth_equiv * 0.45
            if meta["category"] == "Lending":
                base *= 1.3   # lending liquidations accelerate faster
        elif meta["eth_exposure"]:
            base = eth_equiv * 0.20
        else:
            base = base_fear

        return -min((base + base_fear) * cascade, 90)

    if scenario == "eth_crash":
        if name in ETH_COLLATERAL_HEAVY:
            base = param * 0.45
        elif meta["eth_exposure"]:
            base = param * 0.20
        else:
            base = param * 0.05
        multiplier = 1.3 if meta["category"] == "Lending" else 1.0
        return -min(base * multiplier * cascade, 90)

    elif scenario == "tvl_exodus":
        base = param
        if meta["chains_count"] == 1:
            base *= 1.25
        if meta["category"] in ("Yield Aggregator", "CDP"):
            base *= 1.15
        return -min(base * cascade, 95)

    elif scenario == "stablecoin_depeg":
        if name in STABLECOIN_EXPOSED:
            base = param * 2.2
        elif meta.get("eth_exposure"):
            base = param * 0.6
        else:
            base = param * 0.15
        return -min(base * cascade, 85)

    elif scenario == "exploit":
        # This is computed at call time (target-specific), default to 0
        return 0.0

    return 0.0


def _risk_delta(name: str, tvl_impact_pct: float, scenario: str) -> float:
    """Approximate increase in composite risk score from a TVL shock.

    Non-linear: small shocks cause orderly repricing; large shocks trigger
    reflexive selling, oracle failures, and governance paralysis — all of
    which the linear model underestimates."""
    meta       = PROTOCOLS[name]
    abs_impact = abs(tvl_impact_pct)

    # Non-linear base: quadratic above 20% impact
    if abs_impact <= 20:
        base_delta = abs_impact * 0.6
    else:
        base_delta = 20 * 0.6 + (abs_impact - 20) ** 1.4 * 0.08

    # Protocols with prior exploits are more vulnerable during stress
    if meta["exploit_severity"] == 2:
        base_delta *= 1.35
    if not meta["has_timelock"]:
        base_delta *= 1.20

    # Flash crash and BTC crash: governance cannot respond overnight.
    # Flash crash gets a higher speed premium — same loss in 24h vs 30 days
    # means no orderly unwinding, no emergency DAO vote, no circuit breaker.
    if scenario == "flash_crash":
        base_delta *= 1.40
    elif scenario == "btc_crash":
        base_delta *= 1.15

    return round(min(base_delta, 55), 2)


def run_scenario(
    scenario_id:    str,
    param:          float,
    current_scores: dict,
    target_protocol:str | None = None,
    user_holdings:  dict | None = None,
) -> dict:
    scenario = SCENARIOS[scenario_id]
    results  = []
    contagion_victims = set()

    for name, score_data in current_scores.items():
        current_composite = score_data["composite"]

        if scenario_id in ("exploit", "flash_crash"):
            if name == target_protocol:
                impact_pct = -param
            elif target_protocol and name in _CONTAGION.get(target_protocol, []):
                # Flash crash contagion is larger than a quiet exploit —
                # speed of the crash triggers panic exits in correlated pools
                spread = 0.35 if scenario_id == "flash_crash" else 0.25
                impact_pct = -(param * spread)
                contagion_victims.add(name)
            else:
                # Flash crash still causes small market-wide fear outflows
                impact_pct = -(param * 0.05) if scenario_id == "flash_crash" else 0.0
        else:
            impact_pct = _tvl_impact(name, scenario_id, param)

        delta      = _risk_delta(name, impact_pct, scenario_id) if impact_pct != 0 else 0
        new_score  = min(current_composite + delta, 100)

        results.append({
            "protocol":     name,
            "category":     score_data.get("category", ""),
            "current_tvl":  score_data.get("current_tvl", 0),
            "before_score": current_composite,
            "after_score":  round(new_score, 2),
            "score_delta":  round(delta, 2),
            "tvl_impact_pct": round(impact_pct, 2),
            "is_contagion": name in contagion_victims,
            "crosses_threshold": (
                current_composite < THRESHOLDS["medium"] and
                new_score >= THRESHOLDS["medium"]
            ),
        })

    results.sort(key=lambda r: r["score_delta"], reverse=True)

    total_tvl = sum(r["current_tvl"] for r in results if r["current_tvl"])
    market_impact = (
        sum(r["tvl_impact_pct"] * r["current_tvl"] for r in results if r["current_tvl"]) / total_tvl
        if total_tvl else 0
    )

    portfolio_impact = 0.0
    if user_holdings:
        port_total = sum(user_holdings.values())
        if port_total > 0:
            impact_sum = sum(user_holdings.get(r["protocol"], 0) * (r["tvl_impact_pct"]/100.0) for r in results)
            portfolio_impact = (impact_sum / port_total) * 100.0
    else:
        portfolio_impact = market_impact

    return {
        "scenario_id":       scenario_id,
        "scenario_label":    scenario["label"],
        "param":             param,
        "results":           results,
        "portfolio_tvl_impact": round(portfolio_impact, 2),
        "market_tvl_impact": round(market_impact, 2),
        "protocols_breaching_threshold": sum(1 for r in results if r["crosses_threshold"]),
        "max_single_impact": max((r["tvl_impact_pct"] for r in results), default=0),
    }
