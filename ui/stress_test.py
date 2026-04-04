import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PROTOCOLS, THRESHOLDS
from models.stress_tester import SCENARIOS, run_scenario


def _score_color(score: float) -> str:
    if score < THRESHOLDS["low"]:
        return "#3fb950"
    elif score < THRESHOLDS["medium"]:
        return "#e3b341"
    return "#f85149"


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
    result = run_scenario(scenario_id, float(param), scores, target_protocol)
    rows   = result["results"]

    # ── KPI strip ─────────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Portfolio TVL Impact",
        f"{result['portfolio_tvl_impact']:+.1f}%",
        delta=f"{result['portfolio_tvl_impact']:.1f}%",
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
        name="Before",
        y=protocols,
        x=before_sc,
        orientation="h",
        marker_color=[_score_color(s) for s in before_sc],
        opacity=0.45,
        hovertemplate="%{y}<br>Before: %{x:.1f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="After Shock",
        y=protocols,
        x=after_sc,
        orientation="h",
        marker_color=[_score_color(s) for s in after_sc],
        hovertemplate="%{y}<br>After: %{x:.1f}<extra></extra>",
    ))

    # Mark threshold lines
    fig.add_vline(x=THRESHOLDS["low"],    line_dash="dot", line_color="#3fb950",
                  opacity=0.5, annotation_text="Low/Med")
    fig.add_vline(x=THRESHOLDS["medium"], line_dash="dot", line_color="#f85149",
                  opacity=0.5, annotation_text="Med/High")

    fig.update_layout(
        barmode="overlay",
        height=max(280, len(affected) * 28),
        margin=dict(t=20, b=10, l=10, r=80),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22",
        xaxis=dict(range=[0, 105], gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(autorange="reversed", tickfont=dict(color="#e6edf3")),
        legend=dict(bgcolor="#0d1117", font=dict(color="#e6edf3")),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── TVL impact chart ───────────────────────────────────────────────────────
    st.markdown("### Estimated TVL Impact per Protocol")

    impacted = sorted(rows, key=lambda r: r["tvl_impact_pct"])[:15]
    imp_names = [r["protocol"] for r in impacted]
    imp_vals  = [r["tvl_impact_pct"] for r in impacted]
    imp_colors = ["#f85149" if v < -20 else "#f0883e" if v < -10 else "#e3b341"
                  for v in imp_vals]

    fig2 = go.Figure(go.Bar(
        x=imp_vals,
        y=imp_names,
        orientation="h",
        marker_color=imp_colors,
        text=[f"{v:.1f}%" for v in imp_vals],
        textposition="outside",
        textfont=dict(color="#8b949e"),
        hovertemplate="%{y}<br>TVL Impact: %{x:.1f}%<extra></extra>",
    ))
    fig2.add_vline(x=0, line_color="#30363d")
    fig2.update_layout(
        height=max(250, len(impacted) * 28),
        margin=dict(t=10, b=10, l=10, r=80),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22",
        xaxis=dict(gridcolor="#21262d", color="#8b949e", ticksuffix="%"),
        yaxis=dict(autorange="reversed", tickfont=dict(color="#e6edf3")),
        showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ── Detailed results table ─────────────────────────────────────────────────
    st.markdown("### Full Results")

    table_html = """
    <style>
    .st-table { width:100%;border-collapse:collapse;font-size:13px; }
    .st-table th { background:#161b22;color:#8b949e;padding:8px 12px;
                   border-bottom:1px solid #30363d;text-align:left; }
    .st-table td { padding:7px 12px;border-bottom:1px solid #21262d;color:#e6edf3; }
    .st-table tr:hover td { background:#1c2128; }
    .breach-row td { border-left:3px solid #f85149; }
    </style>
    <table class="st-table">
    <tr>
      <th>Protocol</th><th>Category</th>
      <th>Before</th><th>After</th><th>Δ Score</th>
      <th>TVL Impact</th><th>Threshold Breach</th>
    </tr>"""

    for r in sorted(rows, key=lambda x: x["score_delta"], reverse=True):
        breach_class = "breach-row" if r["crosses_threshold"] else ""
        delta_color  = "#f85149" if r["score_delta"] > 15 else \
                       "#e3b341" if r["score_delta"] > 5  else "#8b949e"
        tvl_color    = "#f85149" if r["tvl_impact_pct"] < -20 else \
                       "#e3b341" if r["tvl_impact_pct"] < -5  else "#8b949e"
        contagion    = " 🔗" if r["is_contagion"] else ""
        breach_str   = "<span style='color:#f85149'>YES</span>" if r["crosses_threshold"] else "—"
        table_html  += f"""
        <tr class="{breach_class}">
          <td><b>{r['protocol']}{contagion}</b></td>
          <td style="color:#8b949e">{r['category']}</td>
          <td style="color:{_score_color(r['before_score'])}">{r['before_score']:.1f}</td>
          <td style="color:{_score_color(r['after_score'])}">{r['after_score']:.1f}</td>
          <td style="color:{delta_color}">+{r['score_delta']:.1f}</td>
          <td style="color:{tvl_color}">{r['tvl_impact_pct']:+.1f}%</td>
          <td>{breach_str}</td>
        </tr>"""

    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)
    st.caption("🔗 = second-order contagion from correlated protocol exposure")
