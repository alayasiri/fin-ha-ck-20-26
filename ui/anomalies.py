from datetime import datetime

import plotly.graph_objects as go
import streamlit as st


_SEV_COLOR  = {"low": "#d97706", "medium": "#ea580c", "high": "#dc2626"}
_TYPE_LABEL = {
    "tvl_spike":            "TVL Spike / Drop",
    "multivariate_anomaly": "Multivariate Anomaly",
}


def render(anomalies: dict, scores: dict):
    st.markdown("## Anomaly Detection Feed")

    # Flatten + enrich with protocol context
    flat = []
    for name, events in anomalies.items():
        for ev in events:
            flat.append({**ev, "protocol": name, "category": scores.get(name, {}).get("category","")})

    flat.sort(key=lambda e: e["date"], reverse=True)

    if not flat:
        st.info("No anomalies detected across tracked protocols.")
        return

    # ── Summary ────────────────────────────────────────────────────────────────
    total   = len(flat)
    high    = sum(1 for e in flat if e["severity"] == "high")
    medium  = sum(1 for e in flat if e["severity"] == "medium")
    low     = sum(1 for e in flat if e["severity"] == "low")
    protos  = len({e["protocol"] for e in flat})

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Anomalies",   str(total))
    col2.metric("High Severity",     str(high),   delta=str(high)   if high  else None, delta_color="inverse")
    col3.metric("Medium Severity",   str(medium), delta=str(medium) if medium else None, delta_color="inverse")
    col4.metric("Protocols Affected",str(protos))

    st.divider()

    # ── Filters ────────────────────────────────────────────────────────────────
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        sev_filter = st.multiselect(
            "Severity", ["high", "medium", "low"],
            default=["high", "medium"],
        )
    with col_f2:
        proto_filter = st.multiselect(
            "Protocol", sorted({e["protocol"] for e in flat}),
            default=[],
            placeholder="All protocols",
        )

    filtered = [
        e for e in flat
        if e["severity"] in sev_filter
        and (not proto_filter or e["protocol"] in proto_filter)
    ]

    # ── Anomaly count by protocol bar chart ────────────────────────────────────
    st.markdown("### Anomaly Count by Protocol")

    proto_counts: dict[str, dict] = {}
    for e in filtered:
        p = e["protocol"]
        if p not in proto_counts:
            proto_counts[p] = {"high": 0, "medium": 0, "low": 0}
        proto_counts[p][e["severity"]] += 1

    sorted_protos = sorted(proto_counts, key=lambda p: sum(proto_counts[p].values()), reverse=True)

    fig = go.Figure()
    for sev, color in [("high","#dc2626"),("medium","#ea580c"),("low","#d97706")]:
        fig.add_trace(go.Bar(
            name=sev.capitalize(),
            x=sorted_protos,
            y=[proto_counts[p][sev] for p in sorted_protos],
            marker_color=color,
        ))

    fig.update_layout(
        barmode="stack",
        height=280,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="#f0f4f8",
        plot_bgcolor="#ffffff",
        xaxis=dict(tickangle=-30, tickfont=dict(color="#1e293b"), gridcolor="#e2e8f0"),
        yaxis=dict(gridcolor="#e2e8f0", color="#64748b"),
        legend=dict(bgcolor="#ffffff", font=dict(color="#1e293b")),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Event feed ─────────────────────────────────────────────────────────────
    st.markdown(f"### Event Feed — {len(filtered)} events")

    for ev in filtered[:50]:
        sev   = ev["severity"]
        c     = _SEV_COLOR.get(sev, "#8b949e")
        ttype = _TYPE_LABEL.get(ev["type"], ev["type"])
        pct   = ev.get("pct_change", 0)
        pct_str = f" ({pct:+.1f}%)" if pct else ""

        st.markdown(
            f"""<div style='padding:8px 14px;margin:5px 0;border-left:3px solid {c};
            background:#ffffff;border-radius:0 6px 6px 0;box-shadow:0 1px 3px rgba(0,0,0,0.06)'>
            <div style='display:flex;justify-content:space-between;align-items:center'>
              <span style='font-weight:700;color:#1e293b'>{ev['protocol']}</span>
              <span style='font-size:11px;color:#64748b'>{ev['date']}</span>
            </div>
            <div style='margin-top:3px;font-size:13px'>
              <span style='background:{c}22;color:{c};padding:1px 7px;
                border-radius:10px;font-size:11px;font-weight:600'>{sev.upper()}</span>
              &nbsp;<span style='color:#64748b'>{ttype}</span>
            </div>
            <div style='margin-top:4px;font-size:13px;color:#1e293b'>
              {ev['description']}{pct_str}
            </div>
            </div>""",
            unsafe_allow_html=True,
        )

    if len(filtered) > 50:
        st.caption(f"Showing 50 of {len(filtered)} events. Apply filters to narrow results.")

    # ── Z-score distribution ───────────────────────────────────────────────────
    z_scores = [e["z_score"] for e in filtered if isinstance(e.get("z_score"), (int, float))]
    if z_scores:
        st.markdown("### Z-Score Distribution of Flagged Events")
        fig2 = go.Figure(go.Histogram(
            x=z_scores,
            nbinsx=20,
            marker_color="#2563eb",
            opacity=0.8,
        ))
        fig2.add_vline(x=-2.5, line_dash="dot", line_color="#dc2626", opacity=0.7,
                       annotation_text="−2.5σ threshold")
        fig2.add_vline(x=2.5, line_dash="dot", line_color="#dc2626", opacity=0.7,
                       annotation_text="+2.5σ threshold")
        fig2.update_layout(
            height=220,
            margin=dict(t=10, b=10, l=10, r=10),
            paper_bgcolor="#f0f4f8",
            plot_bgcolor="#ffffff",
            xaxis=dict(title="Z-Score", color="#64748b", gridcolor="#e2e8f0"),
            yaxis=dict(title="Count", gridcolor="#e2e8f0", color="#64748b"),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)
