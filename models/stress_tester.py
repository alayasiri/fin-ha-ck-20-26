"""
Four stress scenarios that simulate market shocks and estimate
per-protocol TVL impact + risk score deterioration.

Scenarios
─────────
  eth_crash        — ETH price drops N%, triggers liquidation cascades
  tvl_exodus       — Mass withdrawal of M% of TVL across DeFi
  stablecoin_depeg — Major stablecoin loses P% of its peg
  exploit          — Simulated smart contract drain on a target protocol
"""
from config import (
    ETH_COLLATERAL_HEAVY,
    PROTOCOLS,
    STABLECOIN_EXPOSED,
    THRESHOLDS,
)

SCENARIOS = {
    "eth_crash": {
        "label":       "ETH Price Crash",
        "description": "Simulates a sharp ETH price drawdown triggering liquidation cascades "
                       "across ETH-collateralised lending and staking protocols.",
        "param_label": "ETH price drop (%)",
        "param_range": (10, 70),
        "param_default": 40,
    },
    "tvl_exodus": {
        "label":       "DeFi Liquidity Exodus",
        "description": "Models coordinated withdrawal pressure — e.g. from a macro risk-off event "
                       "or a loss of confidence in DeFi broadly.",
        "param_label": "TVL outflow (%)",
        "param_range": (5, 60),
        "param_default": 30,
    },
    "stablecoin_depeg": {
        "label":       "Stablecoin Depeg",
        "description": "A major stablecoin (e.g. USDC/USDT) trades at a discount, causing "
                       "pool imbalances and collateral devaluations in exposed protocols.",
        "param_label": "Depeg magnitude (%)",
        "param_range": (1, 25),
        "param_default": 8,
    },
    "exploit": {
        "label":       "Smart Contract Exploit",
        "description": "Simulates a targeted exploit that drains a proportion of a protocol's "
                       "TVL, with second-order contagion to closely-correlated protocols.",
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


def _tvl_impact(name: str, scenario: str, param: float) -> float:
    """Estimated % TVL change for a protocol under a scenario."""
    meta = PROTOCOLS[name]

    if scenario == "eth_crash":
        if name in ETH_COLLATERAL_HEAVY:
            # Heavy ETH exposure → direct liquidation pressure
            base = param * 0.45
        elif meta["eth_exposure"]:
            base = param * 0.20
        else:
            base = param * 0.05
        # Lending platforms liquidate faster than DEXes
        multiplier = 1.3 if meta["category"] == "Lending" else 1.0
        return -min(base * multiplier, 90)

    elif scenario == "tvl_exodus":
        # Everyone bleeds, but single-chain and lower-liquidity protocols bleed more
        base = param
        if meta["chains_count"] == 1:
            base *= 1.25
        if meta["category"] in ("Yield Aggregator", "CDP"):
            base *= 1.15
        return -min(base, 95)

    elif scenario == "stablecoin_depeg":
        if name in STABLECOIN_EXPOSED:
            base = param * 2.2   # pool imbalances amplify depeg
        elif meta.get("eth_exposure"):
            base = param * 0.6
        else:
            base = param * 0.15
        return -min(base, 85)

    elif scenario == "exploit":
        # This is computed at call time (target-specific), default to 0
        return 0.0

    return 0.0


def _risk_delta(name: str, tvl_impact_pct: float, scenario: str) -> float:
    """Approximate increase in composite risk score from a TVL shock."""
    meta = PROTOCOLS[name]
    base_delta = abs(tvl_impact_pct) * 0.6

    # Protocols with already-elevated SC risk amplify impact
    if meta["exploit_severity"] == 2:
        base_delta *= 1.3
    if not meta["has_timelock"]:
        base_delta *= 1.15

    return round(min(base_delta, 50), 2)


def run_scenario(
    scenario_id:    str,
    param:          float,
    current_scores: dict,
    target_protocol:str | None = None,
) -> dict:
    scenario = SCENARIOS[scenario_id]
    results  = []
    contagion_victims = set()

    for name, score_data in current_scores.items():
        current_composite = score_data["composite"]

        if scenario_id == "exploit":
            if name == target_protocol:
                impact_pct = -param
            elif target_protocol and name in _CONTAGION.get(target_protocol, []):
                impact_pct = -(param * 0.25)
                contagion_victims.add(name)
            else:
                impact_pct = 0.0
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

    total_tvl      = sum(r["current_tvl"] for r in results if r["current_tvl"])
    weighted_impact = (
        sum(r["tvl_impact_pct"] * r["current_tvl"] for r in results if r["current_tvl"]) / total_tvl
        if total_tvl else 0
    )

    return {
        "scenario_id":       scenario_id,
        "scenario_label":    scenario["label"],
        "param":             param,
        "results":           results,
        "portfolio_tvl_impact": round(weighted_impact, 2),
        "protocols_breaching_threshold": sum(1 for r in results if r["crosses_threshold"]),
        "max_single_impact": max((r["tvl_impact_pct"] for r in results), default=0),
    }
