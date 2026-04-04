import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PROTOCOLS, THRESHOLDS
from models.stress_tester import SCENARIOS, run_scenario


def _score_color(score: float) -> str:
    if score < THRESHOLDS["low"]:
        return "#16a34a"
    elif score < THRESHOLDS["medium"]:
        return "#d97706"
    return "#dc2626"


def render(scores: dict):
    st.markdown("## Stress Test Simulator")
    st.caption(
        "Simulate market shocks and measure protocol resilience. "
        "Impact is estimated from TVL composition, collateral exposure, and governance structure."
    )

    # ── Scenario selector ──────────────────────────────────────────────────────
    scenario_labels = {sid: s["label"] for sid, s in SCENARIOS.items()}
    selected_label  = st.radio(
        "Select Scenario",
        list(scenario_labels.values()),
        horizontal=True,
        label_visibility="collapsed",
    )
    scenario_id = next(k for k, v in scenario_labels.items() if v == selected_label)
    scenario    = SCENARIOS[scenario_id]

    st.markdown(f"_{scenario['description']}_")
    st.markdown("")

    # ── Parameters ────────────────────────────────────────────────────────────
    col_param, col_target = st.columns([2, 2])

    with col_param:
        lo, hi   = scenario["param_range"]
        param    = st.slider(
            scenario["param_label"],
            min_value=lo,
            max_value=hi,
            value=scenario["param_default"],
            step=1,
        )

    target_protocol = None
    with col_target:
        if scenario_id in ("exploit", "flash_crash"):
            label = "Target Protocol"
            target_protocol = st.selectbox(
                label,
                list(scores.keys()),
                index=0,
            )

    # ── Run simulation ─────────────────────────────────────────────────────────
    user_holdings = st.session_state.get("portfolio_holdings", {})
    result = run_scenario(scenario_id, float(param), scores, target_protocol, user_holdings)
    rows   = result["results"]

    # ── KPI strip ─────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    
    if user_holdings:
        impact_label = "Your Portfolio Impact"
        port_total = sum(user_holdings.values())
        dollar_impact = port_total * (result['portfolio_tvl_impact'] / 100.0)
        val_str = f"{result['portfolio_tvl_impact']:+.1f}%"
        delta_str = f"${dollar_impact:,.0f} estimated loss"
    else:
        impact_label = "DeFi Market TVL Impact"
        val_str = f"{result['portfolio_tvl_impact']:+.1f}%"
        delta_str = f"{result['portfolio_tvl_impact']:.1f}%"

    col1.metric(
        impact_label,
        val_str,
        delta=delta_str,
        delta_color="inverse",
    )
    col2.metric(
        "Protocols Crossing Risk Threshold",
        str(result["protocols_breaching_threshold"]),
    )
    col3.metric(
        "Worst Single Protocol Impact",
        f"{result['max_single_impact']:.1f}%",
    )

    st.divider()

    # ── Before / After score chart ─────────────────────────────────────────────
    st.markdown("### Risk Score — Before vs After Shock")

    affected = [r for r in rows if r["score_delta"] > 0.5][:15]
    if not affected:
        affected = rows[:15]

    protocols  = [r["protocol"] for r in affected]
    before_sc  = [r["before_score"] for r in affected]
    after_sc   = [r["after_score"]  for r in affected]
    deltas     = [r["score_delta"]  for r in affected]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Current",
        y=protocols,
        x=before_sc,
        orientation="h",
        marker_color=[_score_color(s) for s in before_sc],
        marker_pattern_shape="/",
        hovertemplate="%{y}<br>Current: %{x:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="After Shock",
        y=protocols,
        x=after_sc,
        orientation="h",
        marker_color=[_score_color(s) for s in after_sc],
        hovertemplate="%{y}<br>After Shock: %{x:.1f}<extra></extra>",
    ))

    # Mark threshold lines
    fig.add_vline(x=THRESHOLDS["low"],    line_dash="dot", line_color="#16a34a",
                  opacity=0.5, annotation_text="Low/Med")
    fig.add_vline(x=THRESHOLDS["medium"], line_dash="dot", line_color="#dc2626",
                  opacity=0.5, annotation_text="Med/High")

    fig.update_layout(
        barmode="group",
        height=max(280, len(affected) * 40),
        margin=dict(t=20, b=10, l=10, r=80),
        paper_bgcolor="#f0f4f8",
        plot_bgcolor="#ffffff",
        xaxis=dict(range=[0, 105], gridcolor="#e2e8f0", color="#64748b"),
        yaxis=dict(autorange="reversed", tickfont=dict(color="#1e293b")),
        legend=dict(bgcolor="#ffffff", font=dict(color="#1e293b")),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── TVL impact chart ───────────────────────────────────────────────────────
    st.markdown("### Estimated TVL Impact per Protocol")

    impacted = sorted(rows, key=lambda r: r["tvl_impact_pct"])[:15]
    imp_names = [r["protocol"] for r in impacted]
    imp_vals  = [r["tvl_impact_pct"] for r in impacted]
    imp_colors = ["#dc2626" if v < -20 else "#ea580c" if v < -10 else "#d97706"
                  for v in imp_vals]

    fig2 = go.Figure(go.Bar(
        x=imp_vals,
        y=imp_names,
        orientation="h",
        marker_color=imp_colors,
        text=[f"{v:.1f}%" for v in imp_vals],
        textposition="outside",
        textfont=dict(color="#64748b"),
        hovertemplate="%{y}<br>TVL Impact: %{x:.1f}%<extra></extra>",
    ))
    fig2.add_vline(x=0, line_color="#cbd5e1")
    fig2.update_layout(
        height=max(250, len(impacted) * 28),
        margin=dict(t=10, b=10, l=10, r=80),
        paper_bgcolor="#f0f4f8",
        plot_bgcolor="#ffffff",
        xaxis=dict(gridcolor="#e2e8f0", color="#64748b", ticksuffix="%"),
        yaxis=dict(autorange="reversed", tickfont=dict(color="#1e293b")),
        showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ── Detailed results table ─────────────────────────────────────────────────
    st.markdown("### Full Results")

    has_holdings = bool(user_holdings)
    holding_headers = "<th>Holding (USD)</th><th>Est. Loss</th>" if has_holdings else ""

    table_html = """
<style>
.st-table { width:100%;border-collapse:collapse;font-size:13px; }
.st-table th { background:#f1f5f9;color:#64748b;padding:8px 12px;
               border-bottom:1px solid #cbd5e1;text-align:left; }
.st-table td { padding:7px 12px;border-bottom:1px solid #e2e8f0;color:#1e293b; }
.st-table tr:hover td { background:#f8fafc; }
.breach-row td { border-left:3px solid #dc2626; }
</style>
<table class="st-table">
<tr>
  <th>Protocol</th><th>Category</th>
  <th>Before</th><th>After</th><th>Δ Score</th>
  <th>TVL Impact</th>""" + holding_headers + """<th>Threshold Breach</th>
</tr>"""

    for r in sorted(rows, key=lambda x: x["score_delta"], reverse=True):
        breach_class = "breach-row" if r["crosses_threshold"] else ""
        delta_color  = "#dc2626" if r["score_delta"] > 15 else \
                       "#d97706" if r["score_delta"] > 5  else "#64748b"
        tvl_color    = "#dc2626" if r["tvl_impact_pct"] < -20 else \
                       "#d97706" if r["tvl_impact_pct"] < -5  else "#64748b"
        contagion    = " [contagion]" if r["is_contagion"] else ""
        breach_str   = "<span style='color:#dc2626'>YES</span>" if r["crosses_threshold"] else "—"

        holding_tds = ""
        if has_holdings:
            val = user_holdings.get(r['protocol'], 0.0)
            if val > 0:
                loss = val * (r['tvl_impact_pct'] / 100.0)
                loss_color = "#dc2626" if loss < 0 else "#1e293b"
                holding_tds = f"<td style='color:#1e293b'>${val:,.0f}</td><td style='color:{loss_color}'>${loss:,.0f}</td>"
            else:
                holding_tds = "<td style='color:#64748b'>—</td><td style='color:#64748b'>—</td>"

        table_html  += f"""
<tr class="{breach_class}">
  <td><b>{r['protocol']}{contagion}</b></td>
  <td style="color:#64748b">{r['category']}</td>
  <td style="color:{_score_color(r['before_score'])}">{r['before_score']:.1f}</td>
  <td style="color:{_score_color(r['after_score'])}">{r['after_score']:.1f}</td>
  <td style="color:{delta_color}">+{r['score_delta']:.1f}</td>
  <td style="color:{tvl_color}">{r['tvl_impact_pct']:+.1f}%</td>
  {holding_tds}
  <td>{breach_str}</td>
</tr>"""

    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)
    st.caption("[contagion] = second-order contagion from correlated protocol exposure")
