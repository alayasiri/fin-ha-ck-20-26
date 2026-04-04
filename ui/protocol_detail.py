from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import PROTOCOLS, THRESHOLDS
from data.fetcher import fetch_price_history


def _color(score: float) -> str:
    if score < THRESHOLDS["low"]:
        return "#3fb950"
    elif score < THRESHOLDS["medium"]:
        return "#e3b341"
    return "#f85149"


def render(protocol_name: str, scores: dict, tvl_data: dict, anomalies: dict):
    if protocol_name not in scores:
        st.warning("No data yet. Try refreshing.")
        return

    data  = scores[protocol_name]
    meta  = PROTOCOLS[protocol_name]
    anom  = anomalies.get(protocol_name, [])
    score = data["composite"]

    # Header
    col_title, col_gauge = st.columns([2, 1])

    with col_title:
        st.markdown(f"## {protocol_name}")
        st.markdown(
            f"`{meta['category']}` · `{meta['chain']}` · Token: **{meta['token']}**"
        )
        signal = data.get("signal", "HOLD")
        sig_colors = {"INCREASE":"#3fb950","HOLD":"#58a6ff","REDUCE":"#e3b341","EXIT":"#f85149"}
        sig_c = sig_colors.get(signal, "#8b949e")
        st.markdown(
            f"<span style='font-size:22px;font-weight:700;color:{sig_c}'>"
            f"▶ {signal}</span>",
            unsafe_allow_html=True,
        )
        st.caption(data.get("rationale", ""))

    with col_gauge:
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=score,
            number={"font": {"size": 32, "color": _color(score)}, "suffix": ""},
            title={"text": "Risk Score", "font": {"size": 13, "color": "#8b949e"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#8b949e",
                          "tickfont": {"size": 9}, "tickwidth": 1},
                "bar":  {"color": _color(score), "thickness": 0.25},
                "bgcolor": "#161b22",
                "borderwidth": 0,
                "steps": [
                    {"range": [0,  35], "color": "#1a3a2a"},
                    {"range": [35, 60], "color": "#3a2a00"},
                    {"range": [60,100], "color": "#3a1a1a"},
                ],
                "threshold": {
                    "line": {"color": "#e6edf3", "width": 2},
                    "thickness": 0.7,
                    "value": score,
                },
            },
        ))
        fig_gauge.update_layout(
            height=220, margin=dict(t=20, b=0, l=20, r=20),
            paper_bgcolor="#0d1117", font={"color": "#e6edf3"},
        )
        st.plotly_chart(fig_gauge, use_container_width=True)

    st.divider()

    # ── Component scores breakdown ─────────────────────────────────────────────
    st.markdown("### Risk Component Breakdown")

    breakdown = data.get("breakdown", {})
    comp_labels = {
        "liquidity":     "Liquidity Risk",
        "market":        "Market Risk",
        "smart_contract":"Smart Contract Risk",
        "governance":    "Governance Risk",
        "sentiment":     "Sentiment Risk",
    }
    weights = {"liquidity":25,"market":20,"smart_contract":25,"governance":20,"sentiment":10}

    b_names = [comp_labels[k] for k in comp_labels]
    b_scores = [breakdown.get(k, 0) for k in comp_labels]
    b_weights = [weights[k] for k in comp_labels]
    b_colors = [_color(s) for s in b_scores]

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        x=b_scores,
        y=b_names,
        orientation="h",
        marker_color=b_colors,
        text=[f"{s:.1f}" for s in b_scores],
        textposition="outside",
        textfont=dict(color="#e6edf3", size=12),
        customdata=b_weights,
        hovertemplate="<b>%{y}</b><br>Score: %{x:.1f}/100<br>Weight: %{customdata}%<extra></extra>",
    ))
    fig_bar.update_layout(
        height=280,
        xaxis=dict(range=[0, 110], showgrid=True, gridcolor="#21262d",
                   tickfont=dict(color="#8b949e")),
        yaxis=dict(tickfont=dict(color="#e6edf3")),
        margin=dict(t=10, b=10, l=10, r=60),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22",
        showlegend=False,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── TVL history + anomaly markers ─────────────────────────────────────────
    st.markdown("### TVL History")

    tvl_series = sorted(tvl_data.get(protocol_name, []), key=lambda e: e.get("date", 0))
    if tvl_series:
        dates  = [datetime.utcfromtimestamp(e["date"]) for e in tvl_series]
        values = [e.get("totalLiquidityUSD", 0) / 1e9 for e in tvl_series]

        # Anomaly dates for markers
        anom_dates = set(a["date"] for a in anom if a["severity"] in ("medium", "high"))
        anom_x, anom_y = [], []
        for d, v, e in zip(dates, values, tvl_series):
            ds = d.strftime("%Y-%m-%d")
            if ds in anom_dates:
                anom_x.append(d)
                anom_y.append(v)

        fig_tvl = go.Figure()
        fig_tvl.add_trace(go.Scatter(
            x=dates, y=values,
            mode="lines",
            name="TVL",
            line=dict(color="#58a6ff", width=2),
            fill="tozeroy",
            fillcolor="rgba(88,166,255,0.08)",
            hovertemplate="%{x|%Y-%m-%d}<br>TVL: $%{y:.3f}B<extra></extra>",
        ))
        if anom_x:
            fig_tvl.add_trace(go.Scatter(
                x=anom_x, y=anom_y,
                mode="markers",
                name="Anomaly",
                marker=dict(color="#f85149", size=9, symbol="triangle-down",
                            line=dict(color="#e6edf3", width=1)),
                hovertemplate="%{x|%Y-%m-%d}<br>Anomaly detected<extra></extra>",
            ))

        # Peak line
        peak_tvl = data.get("peak_tvl", 0) / 1e9
        if peak_tvl:
            fig_tvl.add_hline(
                y=peak_tvl, line_dash="dot", line_color="#e3b341", opacity=0.6,
                annotation_text=f"Peak ${peak_tvl:.2f}B",
                annotation_font_color="#e3b341",
            )

        fig_tvl.update_layout(
            height=340,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor="#0d1117",
            plot_bgcolor="#161b22",
            xaxis=dict(showgrid=False, color="#8b949e"),
            yaxis=dict(title="TVL ($B)", gridcolor="#21262d", color="#8b949e"),
            legend=dict(bgcolor="#161b22", bordercolor="#30363d", font=dict(color="#e6edf3")),
            hovermode="x unified",
        )
        st.plotly_chart(fig_tvl, use_container_width=True)

        drawdown = data.get("drawdown_pct", 0)
        c1, c2, c3 = st.columns(3)
        c1.metric("Current TVL", f"${data.get('current_tvl', 0)/1e9:.3f}B")
        c2.metric("Peak TVL", f"${peak_tvl:.3f}B")
        c3.metric("Drawdown from Peak", f"{drawdown:.1f}%",
                  delta=f"{-drawdown:.1f}%", delta_color="inverse")
    else:
        st.info("TVL history not available for this protocol.")

    # ── Price history ──────────────────────────────────────────────────────────
    with st.spinner("Loading price data…"):
        px_hist = fetch_price_history(protocol_name)
    if len(px_hist) > 5:
        st.markdown("### Token Price (30d)")
        fig_px = go.Figure(go.Scatter(
            y=px_hist,
            mode="lines",
            line=dict(color="#d2a8ff", width=2),
            fill="tozeroy",
            fillcolor="rgba(210,168,255,0.08)",
            hovertemplate="Day %{x}<br>Price: $%{y:,.2f}<extra></extra>",
        ))
        fig_px.update_layout(
            height=200,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor="#0d1117",
            plot_bgcolor="#161b22",
            xaxis=dict(showgrid=False, color="#8b949e"),
            yaxis=dict(gridcolor="#21262d", color="#8b949e"),
            showlegend=False,
        )
        st.plotly_chart(fig_px, use_container_width=True)

    # ── Static risk factors table ──────────────────────────────────────────────
    st.markdown("### Protocol Risk Factors")

    severity_map  = {0: "None", 1: "Minor (indirect)", 2: "Major exploit"}
    exploit_color = {0: "#3fb950", 1: "#e3b341", 2: "#f85149"}
    sev           = meta["exploit_severity"]

    st.markdown(f"""
    <style>
    .factor-table {{ width:100%;border-collapse:collapse;font-size:13px; }}
    .factor-table td {{ padding:7px 14px;border-bottom:1px solid #21262d;color:#e6edf3; }}
    .factor-table td:first-child {{ color:#8b949e;width:44%; }}
    </style>
    <table class="factor-table">
      <tr><td>Last External Audit</td>
          <td>~{meta['audit_age_days']} days ago</td></tr>
      <tr><td>Exploit History</td>
          <td style="color:{exploit_color[sev]}">{severity_map[sev]}</td></tr>
      <tr><td>Bug Bounty Program</td>
          <td>${meta['bug_bounty_usd']:,}</td></tr>
      <tr><td>Governance Timelock</td>
          <td>{'Yes — ' + str(meta['timelock_days']) + ' day(s)' if meta['has_timelock'] else '<span style="color:#f85149">No</span>'}</td></tr>
      <tr><td>Token Concentration (Gini-est.)</td>
          <td>{meta['token_gini']:.2f}</td></tr>
      <tr><td>Active Chains</td>
          <td>{meta['chains_count']}</td></tr>
      <tr><td>ETH Collateral Exposure</td>
          <td>{'Yes' if meta['eth_exposure'] else 'No'}</td></tr>
    </table>
    """, unsafe_allow_html=True)

    # ── Recent anomalies ───────────────────────────────────────────────────────
    if anom:
        st.markdown("### Detected Anomalies")
        sev_col = {"low": "#e3b341", "medium": "#f0883e", "high": "#f85149"}
        for a in anom[:8]:
            c = sev_col.get(a["severity"], "#8b949e")
            st.markdown(
                f"<div style='padding:6px 12px;margin:4px 0;border-left:3px solid {c};"
                f"background:#161b22;border-radius:0 4px 4px 0;font-size:13px'>"
                f"<span style='color:{c};font-weight:600'>{a['severity'].upper()}</span>"
                f" &nbsp;·&nbsp; {a['date']}"
                f"<br><span style='color:#e6edf3'>{a['description']}</span></div>",
                unsafe_allow_html=True,
            )
