import json
import os
import urllib.request
import plotly.graph_objects as go
import numpy as np
import streamlit as st

from config import PROTOCOLS, THRESHOLDS


_SIG_META = {
    "INCREASE": {"color": "#3fb950", "icon": "▲", "desc": "Strong metrics, consider adding exposure"},
    "HOLD":     {"color": "#58a6ff", "icon": "●", "desc": "Acceptable risk, maintain current positions"},
    "REDUCE":   {"color": "#e3b341", "icon": "▼", "desc": "Elevated risk, trim position size"},
    "EXIT":     {"color": "#f85149", "icon": "✕", "desc": "Risk threshold exceeded, exit or hedge"},
}

_OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")

def _generate_executive_summary(scores: dict) -> str:
    high_risk = [name for name, d in scores.items() if d.get("signal") in ("EXIT", "REDUCE")]
    if not high_risk:
        prompt = "You are a professional financial risk analyst reporting to a portfolio manager. Provide a concise, two-sentence executive summary stating that all tracked protocols are currently stable and outside the high-risk zone. Avoid filler words, emojis, and exaggerated language."
    else:
        prompt = f"You are a professional financial risk analyst reporting to a portfolio manager. Provide a concise, two-sentence executive summary advising caution regarding the following specific assets flagged for immediate risk reduction or exit: {', '.join(high_risk)}. Avoid filler words, emojis, and exaggerated language."

    payload = json.dumps({
        "model":   _OLLAMA_MODEL,
        "prompt":  prompt,
        "stream":  False,
        "options": {"temperature": 0.2},
    }).encode()
    try:
        req = urllib.request.Request(
            f"{_OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
            return resp.get("response", "AI Summary unavailable at the moment.")
    except Exception:
        return "AI Summary engine is currently unreachable. Check local Ollama connection."



def _max_allocation(score: float) -> float:
    """Suggested position cap (% of DeFi portfolio) given composite risk score."""
    if score < 25:
        return 20.0
    elif score < 35:
        return 15.0
    elif score < 50:
        return 8.0
    elif score < 65:
        return 3.0
    return 0.0


def _portfolio_risk_calculator(scores: dict):
    st.markdown("### Your Portfolio Risk Score")
    st.caption(
        "Enter your current holdings to calculate a weighted portfolio risk score "
        "and see which protocols are driving your overall exposure."
    )

    protocol_names = list(scores.keys())
    holdings: dict[str, float] = {}

    with st.expander("Enter holdings (USD)", expanded=True):
        cols = st.columns(4)
        for i, name in enumerate(protocol_names):
            val = cols[i % 4].number_input(
                name, min_value=0.0, value=0.0, step=100.0,
                format="%.0f", key=f"holding_{name}", label_visibility="visible"
            )
            if val > 0:
                holdings[name] = val

    if not holdings:
        st.info("Enter at least one holding above to see your portfolio risk score.")
        return

    total = sum(holdings.values())
    weights = {n: v / total for n, v in holdings.items()}
    port_score = sum(weights[n] * scores[n]["composite"] for n in holdings)
    band = "LOW" if port_score < THRESHOLDS["low"] else \
           ("MEDIUM" if port_score < THRESHOLDS["medium"] else "HIGH")
    band_color = {"LOW": "#3fb950", "MEDIUM": "#e3b341", "HIGH": "#f85149"}[band]

    m1, m2, m3 = st.columns(3)
    m1.metric("Portfolio Risk Score", f"{port_score:.1f} / 100")
    m2.metric("Risk Band", band)
    m3.metric("Total DeFi Exposure", f"${total:,.0f}")

    # Risk contribution breakdown
    contributions = {
        n: weights[n] * scores[n]["composite"]
        for n in holdings
    }
    contrib_sorted = sorted(contributions.items(), key=lambda x: -x[1])

    fig = go.Figure(go.Bar(
        x=[c for _, c in contrib_sorted],
        y=[n for n, _ in contrib_sorted],
        orientation="h",
        marker_color=[
            "#f85149" if scores[n]["composite"] >= THRESHOLDS["medium"] else
            "#e3b341" if scores[n]["composite"] >= THRESHOLDS["low"] else "#3fb950"
            for n, _ in contrib_sorted
        ],
        text=[f"{c:.1f} pts  ({weights[n]*100:.1f}% allocation)"
              for n, c in contrib_sorted],
        textposition="outside",
        textfont=dict(color="#8b949e", size=11),
        hovertemplate="%{y}<br>Risk contribution: %{x:.2f} pts<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="Risk contribution by protocol (weight × score)",
                   font=dict(color="#8b949e", size=12)),
        height=max(220, len(holdings) * 32),
        margin=dict(t=30, b=10, l=10, r=140),
        paper_bgcolor="#0d1117", plot_bgcolor="#161b22",
        xaxis=dict(gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(autorange="reversed", tickfont=dict(color="#e6edf3")),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Flag over-limit allocations
    over_limit = [
        n for n in holdings
        if weights[n] * 100 > _max_allocation(scores[n]["composite"])
    ]
    if over_limit:
        st.warning("**Allocation exceeds suggested cap.** Consider rebalancing to stay within risk-adjusted position limits.")
        for n in over_limit:
            max_pct = _max_allocation(scores[n]["composite"])
            max_usd = total * (max_pct / 100.0)
            over_usd = holdings[n] - max_usd
            st.markdown(f"&nbsp;&nbsp;• **{n}**: Current {weights[n]*100:.1f}% (${holdings[n]:,.0f}) | Max {max_pct:.0f}% (${max_usd:,.0f}) ➔ **Reduce holding by ${over_usd:,.0f}**")

    st.divider()


def render(scores: dict, anomalies: dict):
    st.markdown("## Portfolio Risk Advisor")
    st.caption(
        "Signal-based position guidance derived from the composite risk score, "
        "on-chain anomaly count, and sentiment overlay."
    )

    if st.button("Generate Executive Summary", help="Generate an automated risk overview"):
        with st.spinner("Generating summary..."):
            summary = _generate_executive_summary(scores)
            st.info(f"**Executive Brief:**\n\n{summary}")

    _portfolio_risk_calculator(scores)

    # ── Signal distribution summary ────────────────────────────────────────────
    by_signal: dict[str, list[str]] = {"INCREASE": [], "HOLD": [], "REDUCE": [], "EXIT": []}
    for name, data in scores.items():
        sig = data.get("signal", "HOLD")
        by_signal.setdefault(sig, []).append(name)

    col1, col2, col3, col4 = st.columns(4)
    for col, sig in zip([col1, col2, col3, col4], ["INCREASE","HOLD","REDUCE","EXIT"]):
        m = _SIG_META[sig]
        col.markdown(
            f"<div style='padding:12px;background:#161b22;border-radius:8px;"
            f"border-top:3px solid {m['color']};text-align:center'>"
            f"<div style='font-size:22px;font-weight:700;color:{m['color']}'>"
            f"{m['icon']} {len(by_signal[sig])}</div>"
            f"<div style='color:#8b949e;font-size:12px;margin-top:4px'>{sig}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Signal table ───────────────────────────────────────────────────────────
    st.markdown("### Position Signals")

    # Sort: EXIT first, then REDUCE, HOLD, INCREASE — secondary by score desc
    sig_order = {"EXIT": 0, "REDUCE": 1, "HOLD": 2, "INCREASE": 3}
    sorted_rows = sorted(
        scores.items(),
        key=lambda kv: (sig_order.get(kv[1].get("signal","HOLD"), 2), -kv[1]["composite"])
    )

    for name, data in sorted_rows:
        sig    = data.get("signal", "HOLD")
        m      = _SIG_META[sig]
        score  = data["composite"]
        anom   = len(anomalies.get(name, []))
        alloc  = _max_allocation(score)
        cat    = data.get("category", "")
        ch7    = data.get("change_7d", 0)
        ch7_c  = "#3fb950" if ch7 > 0 else "#f85149"

        with st.container():
            st.markdown(
                f"""<div style='padding:10px 14px;margin:4px 0;background:#161b22;
                border-radius:8px;border-left:4px solid {m['color']}'>
                <div style='display:flex;justify-content:space-between;align-items:flex-start'>
                  <div>
                    <span style='font-weight:700;font-size:15px;color:#e6edf3'>{name}</span>
                    &nbsp;<span style='color:#8b949e;font-size:12px'>{cat}</span>
                    {'&nbsp;<span style="color:#f85149;font-size:11px">⚠ '+str(anom)+' anomaly</span>' if anom else ''}
                  </div>
                  <div style='text-align:right'>
                    <span style='font-size:18px;font-weight:700;color:{m['color']}'>{m['icon']} {sig}</span>
                    <br><span style='font-size:11px;color:#8b949e'>Max allocation: {alloc:.0f}%</span>
                  </div>
                </div>
                <div style='margin-top:6px;font-size:12px;color:#8b949e'>
                  Risk score: <span style='color:#e6edf3'>{score:.1f}</span> &nbsp;·&nbsp;
                  7d TVL: <span style='color:{ch7_c}'>{ch7:+.1f}%</span> &nbsp;·&nbsp;
                  {data.get('rationale','')}
                </div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.divider()

    # ── Risk budget chart ──────────────────────────────────────────────────────
    st.markdown("### Suggested Position Caps (% of DeFi Portfolio)")

    cap_data = [(n, _max_allocation(d["composite"])) for n, d in sorted_rows]
    cap_data.sort(key=lambda x: -x[1])
    names_c = [r[0] for r in cap_data if r[1] > 0]
    allocs_c = [r[1] for r in cap_data if r[1] > 0]
    colors_c = [_SIG_META[scores[n].get("signal","HOLD")]["color"] for n in names_c]

    fig = go.Figure(go.Bar(
        x=allocs_c,
        y=names_c,
        orientation="h",
        marker_color=colors_c,
        text=[f"{a:.0f}%" for a in allocs_c],
        textposition="outside",
        textfont=dict(color="#8b949e"),
        hovertemplate="%{y}<br>Max allocation: %{x}%<extra></extra>",
    ))
    fig.update_layout(
        height=max(280, len(names_c) * 28),
        margin=dict(t=10, b=10, l=10, r=60),
        paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22",
        xaxis=dict(gridcolor="#21262d", color="#8b949e", ticksuffix="%", range=[0,25]),
        yaxis=dict(autorange="reversed", tickfont=dict(color="#e6edf3")),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Risk score correlation heatmap ─────────────────────────────────────────
    st.markdown("### Protocol Risk Correlation Matrix")
    st.caption("Built from shared risk factor exposure (chain, collateral type, category).")

    # Encode protocol characteristics as feature vectors, compute cosine similarity
    all_names = list(scores.keys())
    chains    = sorted({PROTOCOLS[n]["chain"] for n in all_names})
    cats      = sorted({PROTOCOLS[n]["category"] for n in all_names})

    def feature_vec(name):
        meta = PROTOCOLS[name]
        chain_enc = [1 if meta["chain"] == c else 0 for c in chains]
        cat_enc   = [1 if meta["category"] == c else 0 for c in cats]
        eth_enc   = [1 if meta["eth_exposure"] else 0]
        score_enc = [scores[name]["composite"] / 100]
        return chain_enc + cat_enc + eth_enc + score_enc

    mat = np.array([feature_vec(n) for n in all_names], dtype=float)
    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    normed = mat / norms
    corr = normed @ normed.T

    fig2 = go.Figure(go.Heatmap(
        z=corr,
        x=all_names,
        y=all_names,
        colorscale=[
            [0.0, "#0d1117"],
            [0.4, "#1f3a5f"],
            [0.7, "#1a7f37"],
            [1.0, "#f85149"],
        ],
        zmin=0, zmax=1,
        hovertemplate="%{y} ↔ %{x}<br>Similarity: %{z:.2f}<extra></extra>",
        showscale=True,
        colorbar=dict(thickness=12, tickfont=dict(color="#8b949e")),
    ))
    fig2.update_layout(
        height=520,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="#0d1117",
        xaxis=dict(tickangle=-45, tickfont=dict(size=10, color="#8b949e")),
        yaxis=dict(tickfont=dict(size=10, color="#8b949e")),
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ── Actionable summary ─────────────────────────────────────────────────────
    st.markdown("### Key Takeaways")

    exits   = by_signal.get("EXIT",   [])
    reduces = by_signal.get("REDUCE", [])
    adds    = by_signal.get("INCREASE",[])

    if exits:
        st.error(f"**Exit positions:** {', '.join(exits)} — risk scores exceed safe threshold.")
    if reduces:
        st.warning(f"**Reduce exposure:** {', '.join(reduces)} — risk elevated, trim recommended.")
    if adds:
        st.success(f"**Potential adds:** {', '.join(adds)} — strong metrics relative to risk.")
    if not exits and not reduces:
        st.info("Portfolio risk is within acceptable bounds across all tracked protocols.")
