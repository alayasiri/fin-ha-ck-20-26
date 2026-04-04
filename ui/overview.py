import plotly.graph_objects as go
import streamlit as st
from textwrap import dedent

from config import CATEGORY_COLORS, THRESHOLDS


def _risk_color(score: float) -> str:
    if score < THRESHOLDS["low"]:
        return "#1a7f37"
    elif score < THRESHOLDS["medium"]:
        return "#9a6700"
    return "#cf222e"


def _band_label(score: float) -> str:
    if score < THRESHOLDS["low"]:
        return "LOW"
    elif score < THRESHOLDS["medium"]:
        return "MEDIUM"
    return "HIGH"


def _alert_banner(scores: dict, anomalies: dict):
    exits   = [n for n, v in scores.items() if v["signal"] == "EXIT"]
    reduces = [n for n, v in scores.items() if v["signal"] == "REDUCE"]
    high_anom = [n for n, evs in anomalies.items()
                 if any(e["severity"] == "high" for e in evs)]

    if exits:
        st.error(
            f"**EXIT signal active** — {', '.join(exits)}. "
            "Risk scores have crossed the high-risk threshold. Review positions immediately."
        )
    if reduces:
        st.warning(
            f"**REDUCE signal** — {', '.join(reduces)}. "
            "Elevated risk detected; consider trimming exposure."
        )
    if high_anom:
        names = ", ".join(high_anom)
        st.warning(f"**High-severity anomalies** detected on: {names}.")


def render(scores: dict, anomalies: dict, fear_greed: dict):
    _alert_banner(scores, anomalies)
    st.markdown("## Protocol Risk Overview")
    st.caption(
        "Composite risk score (0–100) across 20 major DeFi protocols, "
        "updated every 24 hours from on-chain data."
    )

    # ── Risk band legend ───────────────────────────────────────────────────────
    st.markdown(
        "<div style='display:flex;gap:10px;margin-bottom:8px'>"
        "<span style='background:#1a3a2a;color:#3fb950;padding:3px 12px;"
        "border-radius:12px;font-size:12px;font-weight:600'>● LOW &nbsp;0–35</span>"
        "<span style='background:#3a2a00;color:#e3b341;padding:3px 12px;"
        "border-radius:12px;font-size:12px;font-weight:600'>● MEDIUM &nbsp;35–60</span>"
        "<span style='background:#3a1a1a;color:#f85149;padding:3px 12px;"
        "border-radius:12px;font-size:12px;font-weight:600'>● HIGH &nbsp;60–100</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    with st.expander("How are scores calculated?", expanded=False):
        st.markdown("""
| Component | Weight | What it measures |
|-----------|--------|-----------------|
| Liquidity Risk | 25% | TVL drawdown from peak, 7-day and 30-day trend |
| Smart Contract Risk | 25% | Audit age, exploit history, bug bounty size |
| Governance Risk | 20% | Token concentration, timelock presence, chain governance |
| Market Risk | 20% | Token price volatility and 30-day return |
| Sentiment Risk | 10% | Crypto Fear & Greed index + protocol news tone |

**Signal thresholds:** INCREASE < 30 · HOLD 30–45 · REDUCE 45–65 · EXIT > 65
        """)

    # ── Top metrics row ────────────────────────────────────────────────────────
    total_tvl  = sum(v.get("current_tvl", 0) for v in scores.values())
    high_risk  = sum(1 for v in scores.values() if v["composite"] >= THRESHOLDS["medium"])
    anom_total = sum(len(a) for a in anomalies.values())
    fng_val    = fear_greed.get("value", 50)
    fng_label  = fear_greed.get("label", "Neutral")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total TVL Tracked", f"${total_tvl / 1e9:.2f}B",
                  help="Sum of current TVL across all 20 tracked protocols")
    with col2:
        st.metric("High-Risk Protocols", f"{high_risk} / {len(scores)}",
                  help="Protocols with composite risk score ≥ 60")
    with col3:
        st.metric("Active Anomalies", str(anom_total),
                  help="Statistically unusual TVL events detected in the last 90 days")
    with col4:
        st.metric(f"Fear & Greed — {fng_label}", str(fng_val),
                  help="Alternative.me Crypto Fear & Greed Index (0=Extreme Fear, 100=Extreme Greed)")

    st.divider()

    # ── Risk treemap ───────────────────────────────────────────────────────────
    st.markdown("### Risk Landscape")
    st.caption("Box size = TVL · Color = risk score · Hover for details")

    labels, parents, values, colors, customdata = [], [], [], [], []
    for name, data in scores.items():
        score = data["composite"]
        tvl   = max(data.get("current_tvl", 1e6), 1e6)
        labels.append(name)
        parents.append(data["category"])
        values.append(tvl)
        colors.append(score)
        customdata.append([
            score,
            _band_label(score),
            f"${tvl / 1e9:.2f}B" if tvl >= 1e9 else f"${tvl / 1e6:.0f}M",
            data.get("change_7d", 0),
            data.get("signal", "—"),
        ])

    # Category parents
    categories = list({d["category"] for d in scores.values()})
    for cat in categories:
        labels.append(cat)
        parents.append("")
        values.append(0)
        colors.append(0)
        customdata.append([0, "", "", 0, ""])

    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=parents,
        values=values,
        customdata=customdata,
        marker=dict(
            colors=colors,
            colorscale=[
                [0.0,  "#1a7f37"],
                [0.35, "#3fb950"],
                [0.55, "#e3b341"],
                [0.75, "#f0883e"],
                [1.0,  "#cf222e"],
            ],
            cmin=0,
            cmax=100,
            colorbar=dict(
                title=dict(text="Risk Score", font=dict(color="#8b949e")),
                thickness=14,
                tickfont=dict(color="#8b949e"),
            ),
            line=dict(width=1.5, color="#30363d"),
        ),
        hovertemplate=(
            "<b>%{label}</b><br>"
            "Risk Score: %{customdata[0]:.1f} (%{customdata[1]})<br>"
            "TVL: %{customdata[2]}<br>"
            "7d TVL Change: %{customdata[3]:+.1f}%<br>"
            "Signal: %{customdata[4]}"
            "<extra></extra>"
        ),
        texttemplate="<b>%{label}</b><br>%{customdata[0]:.0f}",
        textfont=dict(size=12, color="#e6edf3"),
    ))
    fig.update_layout(
        height=460,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Risk score table ───────────────────────────────────────────────────────
    st.markdown("### Protocol Risk Scores")
    st.caption("Select a protocol in the sidebar → **Protocol Deep Dive** to see full history and factor breakdown.")

    # Quick-access buttons for high-risk protocols
    high_risk_protocols = [n for n, v in scores.items() if v["composite"] >= THRESHOLDS["medium"]]
    if high_risk_protocols:
        st.markdown(
            "<span style='font-size:12px;color:#f85149;font-weight:600'>High-risk — explore in Deep Dive:</span>",
            unsafe_allow_html=True,
        )
        btn_cols = st.columns(min(len(high_risk_protocols), 5))
        for col, name in zip(btn_cols, high_risk_protocols[:5]):
            if col.button(name, key=f"hr_{name}", help=f"Open {name} in Deep Dive"):
                st.session_state.active_protocol = name
                st.session_state.active_page = "Protocol Deep Dive"
                st.rerun()

    col_sort, _ = st.columns([2, 5])
    sort_key = col_sort.selectbox(
        "Sort by", ["Risk Score", "TVL", "7d TVL Change", "Signal"],
        label_visibility="collapsed",
        help="Change the column used to sort the table",
    )

    rows = []
    for name, data in scores.items():
        rows.append({
            "Protocol":      name,
            "Category":      data["category"],
            "Risk Score":    data["composite"],
            "Band":          _band_label(data["composite"]),
            "TVL":           data.get("current_tvl", 0),
            "7d Change":     data.get("change_7d", 0),
            "Drawdown":      data.get("drawdown_pct", 0),
            "Signal":        data.get("signal", "—"),
            "Anomalies":     len(anomalies.get(name, [])),
        })

    key_map = {
        "Risk Score":    ("Risk Score", True),
        "TVL":           ("TVL", True),
        "7d TVL Change": ("7d Change", False),
        "Signal":        ("Signal", True),
    }
    sort_col, reverse = key_map[sort_key]
    rows.sort(key=lambda r: r[sort_col], reverse=reverse)

    # Custom HTML table for visual richness
    table_html = dedent("""
    <style>
    .risk-table { width:100%; border-collapse:collapse; font-size:13px; }
    .risk-table th { background:#161b22; color:#8b949e; padding:8px 12px;
                     text-align:left; border-bottom:1px solid #30363d; }
    .risk-table td { padding:8px 12px; border-bottom:1px solid #21262d;
                     color:#e6edf3; }
    .risk-table tr:hover td { background:#1c2128; }
    .badge { padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600; }
    .badge-low    { background:#1a3a2a; color:#3fb950; }
    .badge-medium { background:#3a2a00; color:#e3b341; }
    .badge-high   { background:#3a1a1a; color:#f85149; }
    .sig-increase { color:#3fb950; font-weight:700; }
    .sig-hold     { color:#58a6ff; font-weight:700; }
    .sig-reduce   { color:#e3b341; font-weight:700; }
    .sig-exit     { color:#f85149; font-weight:700; }
    .score-bar-wrap { display:flex; align-items:center; gap:8px; }
    .score-bar { height:6px; border-radius:3px; display:inline-block; }
    </style>
    <table class="risk-table">
    <tr>
      <th>#</th><th>Protocol</th><th>Category</th>
      <th>Risk Score</th><th>Band</th>
      <th>TVL</th><th>7d Δ TVL</th><th>Drawdown</th>
      <th>Signal</th><th>Anomalies</th>
    </tr>
        """)

    sig_class = {"INCREASE":"sig-increase","HOLD":"sig-hold","REDUCE":"sig-reduce","EXIT":"sig-exit"}
    band_class = {"LOW":"badge-low","MEDIUM":"badge-medium","HIGH":"badge-high"}

    for i, r in enumerate(rows, 1):
        score     = r["Risk Score"]
        bar_color = _risk_color(score)
        bar_pct   = int(score)
        tvl_str   = f"${r['TVL']/1e9:.2f}B" if r["TVL"] >= 1e9 else f"${r['TVL']/1e6:.0f}M"
        ch7_str   = f"{r['7d Change']:+.1f}%"
        ch7_color = "#3fb950" if r["7d Change"] > 0 else "#f85149"
        dd_str    = f"{r['Drawdown']:.1f}%"
        band      = r["Band"]
        sig       = r["Signal"]

        table_html += dedent(f"""
        <tr>
          <td style="color:#8b949e">{i}</td>
          <td><b>{r['Protocol']}</b></td>
          <td style="color:#8b949e">{r['Category']}</td>
          <td>
            <div class="score-bar-wrap">
              <span>{score:.1f}</span>
              <div class="score-bar" style="width:{bar_pct}px;background:{bar_color}"></div>
            </div>
          </td>
          <td><span class="badge {band_class.get(band,'')}">{band}</span></td>
          <td>{tvl_str}</td>
          <td style="color:{ch7_color}">{ch7_str}</td>
          <td style="color:#8b949e">{dd_str}</td>
          <td class="{sig_class.get(sig,'')}">{sig}</td>
          <td style="color:{'#f85149' if r['Anomalies'] else '#8b949e'}">{r['Anomalies'] or '—'}</td>
                </tr>""")

    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)

    # ── FNG history sparkline ──────────────────────────────────────────────────
    history = fear_greed.get("history", [])
    if len(history) > 1:
        st.markdown("### Market Sentiment — 7-Day Fear & Greed")
        fig2 = go.Figure(go.Scatter(
            y=list(reversed(history)),
            mode="lines+markers",
            line=dict(color="#58a6ff", width=2),
            marker=dict(size=6, color="#58a6ff"),
            fill="tozeroy",
            fillcolor="rgba(88,166,255,0.1)",
        ))
        fig2.add_hline(y=25, line_dash="dot", line_color="#f85149", opacity=0.5,
                       annotation_text="Extreme Fear", annotation_font_color="#f85149")
        fig2.add_hline(y=75, line_dash="dot", line_color="#3fb950", opacity=0.5,
                       annotation_text="Extreme Greed", annotation_font_color="#3fb950")
        fig2.update_layout(
            height=160, margin=dict(t=10, b=10, l=0, r=0),
            paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
            yaxis=dict(range=[0, 100], gridcolor="#21262d", color="#8b949e"),
            xaxis=dict(showgrid=False, color="#8b949e"),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
