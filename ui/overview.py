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
    exits     = [n for n, v in scores.items() if v["signal"] == "EXIT"]
    reduces   = [n for n, v in scores.items() if v["signal"] == "REDUCE"]
    high_anom = [n for n, evs in anomalies.items()
                 if any(e["severity"] == "high" for e in evs)]

    alerts = []
    if exits:
        alerts.append((
            "#dc2626", "#fef2f2",
            "EXIT",
            f"{', '.join(exits)} — risk scores exceed safe threshold",
        ))
    if reduces:
        alerts.append((
            "#d97706", "#fffbeb",
            "REDUCE",
            f"{', '.join(reduces)} — elevated risk, consider trimming",
        ))
    if high_anom:
        alerts.append((
            "#ea580c", "#fff7ed",
            "ANOMALY",
            f"High-severity on-chain activity: {', '.join(high_anom)}",
        ))

    if not alerts:
        return

    rows = ""
    for color, bg, tag, msg in alerts:
        rows += (
            f"<div style='display:flex;align-items:center;gap:12px;"
            f"background:{bg};border-left:3px solid {color};"
            f"padding:9px 14px;border-radius:0 6px 6px 0;margin-bottom:6px'>"
            f"<span style='color:{color};font-size:11px;font-weight:700;"
            f"letter-spacing:.06em;white-space:nowrap'>{tag}</span>"
            f"<span style='color:#1e293b;font-size:13px'>{msg}</span>"
            f"</div>"
        )
    st.markdown(rows, unsafe_allow_html=True)


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
        "<span style='background:#dcfce7;color:#16a34a;padding:3px 12px;"
        "border-radius:12px;font-size:12px;font-weight:600'>● LOW &nbsp;0–35</span>"
        "<span style='background:#fef9c3;color:#d97706;padding:3px 12px;"
        "border-radius:12px;font-size:12px;font-weight:600'>● MEDIUM &nbsp;35–60</span>"
        "<span style='background:#fee2e2;color:#dc2626;padding:3px 12px;"
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
                [0.0,  "#16a34a"],
                [0.35, "#86efac"],
                [0.55, "#fde68a"],
                [0.75, "#fb923c"],
                [1.0,  "#dc2626"],
            ],
            cmin=0,
            cmax=100,
            colorbar=dict(
                title=dict(text="Risk Score", font=dict(color="#64748b")),
                thickness=14,
                tickfont=dict(color="#64748b"),
            ),
            line=dict(width=1.5, color="#e2e8f0"),
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
        textfont=dict(size=12, color="#1e293b"),
    ))
    fig.update_layout(
        height=460,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="#f0f4f8",
        plot_bgcolor="#f0f4f8",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Risk score table ───────────────────────────────────────────────────────
    st.markdown("### Protocol Risk Scores")
    st.caption("Select a protocol in the sidebar → **Protocol Deep Dive** to see full history and factor breakdown.")

    # Quick-access buttons for high-risk protocols
    high_risk_protocols = [n for n, v in scores.items() if v["composite"] >= THRESHOLDS["medium"]]
    if high_risk_protocols:
        st.markdown(
            "<span style='font-size:12px;color:#dc2626;font-weight:600'>High-risk — explore in Deep Dive:</span>",
            unsafe_allow_html=True,
        )
        btn_cols = st.columns(min(len(high_risk_protocols), 5))
        for col, name in zip(btn_cols, high_risk_protocols[:5]):
            if col.button(name, key=f"hr_{name}", help=f"Open {name} in Deep Dive"):
                st.session_state.active_protocol = name
                st.session_state.active_page = "Protocol Deep Dive"
                st.rerun()

    col_sort, col_export, _ = st.columns([2, 2, 4])
    sort_key = col_sort.selectbox(
        "Sort by", ["Risk Score", "TVL", "1d TVL Change", "7d TVL Change", "Signal"],
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
            "1d Change":     data.get("change_1d", 0),
            "7d Change":     data.get("change_7d", 0),
            "Drawdown":      data.get("drawdown_pct", 0),
            "Signal":        data.get("signal", "—"),
            "Anomalies":     len(anomalies.get(name, [])),
        })

    key_map = {
        "Risk Score":    ("Risk Score", True),
        "TVL":           ("TVL", True),
        "1d TVL Change": ("1d Change", False),
        "7d TVL Change": ("7d Change", False),
        "Signal":        ("Signal", True),
    }
    sort_col, reverse = key_map[sort_key]
    rows.sort(key=lambda r: r[sort_col], reverse=reverse)

    import io
    import csv
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=rows[0].keys() if rows else [])
    if rows:
        writer.writeheader()
        writer.writerows(rows)
    col_export.download_button("Export CSV", data=csv_buf.getvalue(), file_name="risk_report.csv", mime="text/csv", use_container_width=True)

    # Custom HTML table for visual richness
    table_html = dedent("""
    <style>
    .risk-table { width:100%; border-collapse:collapse; font-size:13px; }
    .risk-table th { background:#f1f5f9; color:#64748b; padding:8px 12px;
                     text-align:left; border-bottom:1px solid #cbd5e1; }
    .risk-table td { padding:8px 12px; border-bottom:1px solid #e2e8f0;
                     color:#1e293b; }
    .risk-table tr:hover td { background:#f8fafc; }
    .badge { padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600; }
    .badge-low    { background:#dcfce7; color:#16a34a; }
    .badge-medium { background:#fef9c3; color:#d97706; }
    .badge-high   { background:#fee2e2; color:#dc2626; }
    .sig-increase { color:#16a34a; font-weight:700; }
    .sig-hold     { color:#2563eb; font-weight:700; }
    .sig-reduce   { color:#d97706; font-weight:700; }
    .sig-exit     { color:#dc2626; font-weight:700; }
    .score-bar-wrap { display:flex; align-items:center; gap:8px; }
    .score-bar { height:6px; border-radius:3px; display:inline-block; }
    </style>
    <table class="risk-table">
    <tr>
      <th>#</th><th>Protocol</th><th>Category</th>
      <th>Risk Score</th><th>Band</th>
      <th>TVL</th><th>1d Δ</th><th>7d Δ</th><th>Drawdown</th>
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
        ch1       = r["1d Change"]
        ch7       = r["7d Change"]
        ch1_str   = f"{ch1:+.1f}%"
        ch7_str   = f"{ch7:+.1f}%"
        # 1d drop below -5% gets a bright red highlight to flag flash crashes
        ch1_color = "#dc2626" if ch1 < -5 else ("#d97706" if ch1 < 0 else "#16a34a")
        ch7_color = "#dc2626" if ch7 < 0 else "#16a34a"
        dd_str    = f"{r['Drawdown']:.1f}%"
        band      = r["Band"]
        sig       = r["Signal"]

        table_html += dedent(f"""
        <tr>
          <td style="color:#64748b">{i}</td>
          <td><b>{r['Protocol']}</b></td>
          <td style="color:#64748b">{r['Category']}</td>
          <td>
            <div class="score-bar-wrap">
              <span>{score:.1f}</span>
              <div class="score-bar" style="width:{bar_pct}px;background:{bar_color}"></div>
            </div>
          </td>
          <td><span class="badge {band_class.get(band,'')}">{band}</span></td>
          <td>{tvl_str}</td>
          <td style="color:{ch1_color};font-weight:{'700' if ch1 < -5 else '400'}">{ch1_str}</td>
          <td style="color:{ch7_color}">{ch7_str}</td>
          <td style="color:#64748b">{dd_str}</td>
          <td class="{sig_class.get(sig,'')}">{sig}</td>
          <td style="color:{'#dc2626' if r['Anomalies'] else '#64748b'}">{r['Anomalies'] or '—'}</td>
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
            line=dict(color="#2563eb", width=2),
            marker=dict(size=6, color="#2563eb"),
            fill="tozeroy",
            fillcolor="rgba(37,99,235,0.08)",
        ))
        fig2.add_hline(y=25, line_dash="dot", line_color="#dc2626", opacity=0.5,
                       annotation_text="Extreme Fear", annotation_font_color="#dc2626")
        fig2.add_hline(y=75, line_dash="dot", line_color="#16a34a", opacity=0.5,
                       annotation_text="Extreme Greed", annotation_font_color="#16a34a")
        fig2.update_layout(
            height=160, margin=dict(t=10, b=10, l=0, r=0),
            paper_bgcolor="#f0f4f8", plot_bgcolor="#ffffff",
            yaxis=dict(range=[0, 100], gridcolor="#e2e8f0", color="#64748b"),
            xaxis=dict(showgrid=False, color="#64748b"),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
