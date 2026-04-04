from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from config import HISTORICAL_INCIDENTS, PROTOCOLS, THRESHOLDS
from data.fetcher import fetch_price_history


def _color(score: float) -> str:
    if score < THRESHOLDS["low"]:
        return "#16a34a"
    elif score < THRESHOLDS["medium"]:
        return "#d97706"
    return "#dc2626"


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
        sig_colors = {"INCREASE":"#16a34a","HOLD":"#2563eb","REDUCE":"#d97706","EXIT":"#dc2626"}
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
            title={"text": "Risk Score", "font": {"size": 13, "color": "#64748b"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "#64748b",
                          "tickfont": {"size": 9}, "tickwidth": 1},
                "bar":  {"color": _color(score), "thickness": 0.25},
                "bgcolor": "#f1f5f9",
                "borderwidth": 0,
                "steps": [
                    {"range": [0,  35], "color": "#dcfce7"},
                    {"range": [35, 60], "color": "#fef9c3"},
                    {"range": [60,100], "color": "#fee2e2"},
                ],
                "threshold": {
                    "line": {"color": "#1e293b", "width": 2},
                    "thickness": 0.7,
                    "value": score,
                },
            },
        ))
        fig_gauge.update_layout(
            height=220, margin=dict(t=20, b=0, l=20, r=20),
            paper_bgcolor="#f0f4f8", font={"color": "#1e293b"},
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
        textfont=dict(color="#1e293b", size=12),
        customdata=b_weights,
        hovertemplate="<b>%{y}</b><br>Score: %{x:.1f}/100<br>Weight: %{customdata}%<extra></extra>",
    ))
    fig_bar.update_layout(
        height=280,
        xaxis=dict(range=[0, 110], showgrid=True, gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b")),
        yaxis=dict(tickfont=dict(color="#1e293b")),
        margin=dict(t=10, b=10, l=10, r=60),
        paper_bgcolor="#f0f4f8",
        plot_bgcolor="#ffffff",
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
            line=dict(color="#2563eb", width=2),
            fill="tozeroy",
            fillcolor="rgba(37,99,235,0.08)",
            hovertemplate="%{x|%Y-%m-%d}<br>TVL: $%{y:.3f}B<extra></extra>",
        ))
        if anom_x:
            fig_tvl.add_trace(go.Scatter(
                x=anom_x, y=anom_y,
                mode="markers",
                name="Anomaly",
                marker=dict(color="#dc2626", size=9, symbol="triangle-down",
                            line=dict(color="#1e293b", width=1)),
                hovertemplate="%{x|%Y-%m-%d}<br>Anomaly detected<extra></extra>",
            ))

        # Peak line
        peak_tvl = data.get("peak_tvl", 0) / 1e9
        if peak_tvl:
            fig_tvl.add_hline(
                y=peak_tvl, line_dash="dot", line_color="#d97706", opacity=0.6,
                annotation_text=f"Peak ${peak_tvl:.2f}B",
                annotation_font_color="#d97706",
            )

        # Historical incident markers
        for incident in HISTORICAL_INCIDENTS.get(protocol_name, []):
            try:
                inc_dt = datetime.strptime(incident["date"], "%Y-%m-%d")
            except ValueError:
                continue
            line_color = "#dc2626" if incident["severity"] == "major" else "#ea580c"
            fig_tvl.add_vline(
                x=inc_dt.timestamp() * 1000,
                line_dash="dash", line_color=line_color, opacity=0.7,
                annotation_text=incident["label"],
                annotation_font_color=line_color,
                annotation_textangle=-90,
                annotation_font_size=10,
            )

        fig_tvl.update_layout(
            height=340,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor="#f0f4f8",
            plot_bgcolor="#ffffff",
            xaxis=dict(showgrid=False, color="#64748b"),
            yaxis=dict(title="TVL ($B)", gridcolor="#e2e8f0", color="#64748b"),
            legend=dict(bgcolor="#ffffff", bordercolor="#e2e8f0", font=dict(color="#1e293b")),
            hovermode="x unified",
        )
        st.plotly_chart(fig_tvl, use_container_width=True)

        drawdown    = data.get("drawdown_pct", 0)
        utilization = data.get("utilization")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current TVL", f"${data.get('current_tvl', 0)/1e9:.3f}B")
        c2.metric("Peak TVL", f"${peak_tvl:.3f}B")
        c3.metric("Drawdown from Peak", f"{drawdown:.1f}%",
                  delta=f"{-drawdown:.1f}%", delta_color="inverse")
        if utilization is not None:
            util_delta = "high — liquidity risk" if utilization > 80 else "normal"
            c4.metric("Borrow Utilization", f"{utilization:.1f}%",
                      delta=util_delta,
                      delta_color="inverse" if utilization > 80 else "off",
                      help="% of deposited assets currently borrowed. >80% signals liquidity risk.")
        else:
            c4.metric("Borrow Utilization", "N/A",
                      help="Only available for lending protocols")
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
            line=dict(color="#7c3aed", width=2),
            fill="tozeroy",
            fillcolor="rgba(124,58,237,0.08)",
            hovertemplate="Day %{x}<br>Price: $%{y:,.2f}<extra></extra>",
        ))
        fig_px.update_layout(
            height=200,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor="#f0f4f8",
            plot_bgcolor="#ffffff",
            xaxis=dict(showgrid=False, color="#64748b"),
            yaxis=dict(gridcolor="#e2e8f0", color="#64748b"),
            showlegend=False,
        )
        st.plotly_chart(fig_px, use_container_width=True)

    # ── Static risk factors table ──────────────────────────────────────────────
    st.markdown("### Protocol Risk Factors")

    severity_map  = {0: "None", 1: "Minor (indirect)", 2: "Major exploit"}
    exploit_color = {0: "#16a34a", 1: "#d97706", 2: "#dc2626"}
    sev           = meta["exploit_severity"]

    st.markdown(f"""
    <style>
    .factor-table {{ width:100%;border-collapse:collapse;font-size:13px; }}
    .factor-table td {{ padding:7px 14px;border-bottom:1px solid #e2e8f0;color:#1e293b; }}
    .factor-table td:first-child {{ color:#64748b;width:44%; }}
    </style>
    <table class="factor-table">
      <tr><td>Last External Audit</td>
          <td>~{meta['audit_age_days']} days ago</td></tr>
      <tr><td>Exploit History</td>
          <td style="color:{exploit_color[sev]}">{severity_map[sev]}</td></tr>
      <tr><td>Bug Bounty Program</td>
          <td>${meta['bug_bounty_usd']:,}</td></tr>
      <tr><td>Governance Timelock</td>
          <td>{'Yes — ' + str(meta['timelock_days']) + ' day(s)' if meta['has_timelock'] else '<span style="color:#dc2626">No</span>'}</td></tr>
      <tr><td>Token Concentration (Gini-est.)</td>
          <td>{meta['token_gini']:.2f}</td></tr>
      <tr><td>Active Chains</td>
          <td>{meta['chains_count']}</td></tr>
      <tr><td>ETH Collateral Exposure</td>
          <td>{'Yes' if meta['eth_exposure'] else 'No'}</td></tr>
      <tr><td>Governance Proposals (30d)</td>
          <td>{data.get('proposal_count', 0)}</td></tr>
    </table>
    """, unsafe_allow_html=True)

    # ── Protocol comparison ────────────────────────────────────────────────────
    st.divider()
    st.markdown("### Compare with Other Protocols")
    other_protocols = [n for n in scores if n != protocol_name]
    compare_with = st.multiselect(
        "Select up to 3 protocols to overlay",
        other_protocols,
        max_selections=3,
        placeholder="Choose protocols…",
    )

    if compare_with:
        all_compare = [protocol_name] + compare_with
        fig_cmp = go.Figure()
        colors_cmp = ["#2563eb", "#16a34a", "#ea580c", "#7c3aed"]

        for idx, name in enumerate(all_compare):
            series = sorted(tvl_data.get(name, []), key=lambda e: e.get("date", 0))
            if not series:
                continue
            vals  = [e.get("totalLiquidityUSD", 0) for e in series]
            peak  = max(vals) if vals else 1
            norm  = [v / peak * 100 for v in vals]   # % of own peak — fair comparison
            dates = [datetime.utcfromtimestamp(e["date"]) for e in series]
            fig_cmp.add_trace(go.Scatter(
                x=dates, y=norm,
                name=name,
                mode="lines",
                line=dict(color=colors_cmp[idx % len(colors_cmp)], width=2),
                hovertemplate=f"{name}<br>%{{x|%Y-%m-%d}}<br>%{{y:.1f}}% of peak<extra></extra>",
            ))

        fig_cmp.update_layout(
            height=300,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor="#f0f4f8",
            plot_bgcolor="#ffffff",
            xaxis=dict(showgrid=False, color="#64748b"),
            yaxis=dict(title="% of Peak TVL", gridcolor="#e2e8f0", color="#64748b"),
            legend=dict(bgcolor="#ffffff", bordercolor="#e2e8f0", font=dict(color="#1e293b")),
            hovermode="x unified",
        )
        st.plotly_chart(fig_cmp, use_container_width=True)
        st.caption("TVL normalised to each protocol's own peak for a fair side-by-side comparison.")

        # Side-by-side risk scores
        st.markdown("**Risk score comparison**")
        score_cols = st.columns(len(all_compare))
        for col, name in zip(score_cols, all_compare):
            s = scores[name]["composite"]
            band = "LOW" if s < THRESHOLDS["low"] else ("MEDIUM" if s < THRESHOLDS["medium"] else "HIGH")
            col.metric(name, f"{s:.1f}", delta=band,
                       delta_color="normal" if band == "LOW" else "inverse")

    # ── Recent anomalies ───────────────────────────────────────────────────────
    if anom:
        st.markdown("### Detected Anomalies")
        sev_col = {"low": "#d97706", "medium": "#ea580c", "high": "#dc2626"}
        for a in anom[:8]:
            c = sev_col.get(a["severity"], "#64748b")
            st.markdown(
                f"<div style='padding:6px 12px;margin:4px 0;border-left:3px solid {c};"
                f"background:#ffffff;border-radius:0 4px 4px 0;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,0.06)'>"
                f"<span style='color:{c};font-weight:600'>{a['severity'].upper()}</span>"
                f" &nbsp;·&nbsp; {a['date']}"
                f"<br><span style='color:#1e293b'>{a['description']}</span></div>",
                unsafe_allow_html=True,
            )
