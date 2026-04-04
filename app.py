"""
DeFi Risk Intelligence Platform
================================
Entry point — run with:  streamlit run app.py
"""
import os
import streamlit as st

# Inject Streamlit secrets into os.environ so all modules can use os.environ.get()
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(str(_k), str(_v))
except Exception:
    pass

st.set_page_config(
    page_title="DeFi Risk Intelligence",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Global CSS overrides — applied once on load
st.markdown("""
<style>
  /* Tighten default Streamlit padding */
  .block-container { padding-top: 3.5rem; padding-bottom: 1rem; }
  /* Metric card styling */
  [data-testid="metric-container"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }
  [data-testid="metric-container"] label { color: #64748b !important; font-size: 12px; }
  [data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #1e293b !important; font-size: 22px; font-weight: 700;
  }
  /* Sidebar */
  [data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e2e8f0; }
  /* Divider */
  hr { border-color: #e2e8f0; margin: 0.6rem 0; }
  /* Selectbox */
  [data-testid="stSelectbox"] label { color: #64748b; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

from data.fetcher import load_all_data
from data.cache import get_cache
from models.risk_scorer import score_all
from models.anomaly_detector import detect_all_anomalies
from config import THRESHOLDS

import ui.overview as pg_overview
import ui.protocol_detail as pg_detail
import ui.anomalies as pg_anomalies
import ui.stress_test as pg_stress
import ui.portfolio as pg_portfolio
import ui.chat as pg_chat


# ── Session state ──────────────────────────────────────────────────────────────
if "data"             not in st.session_state: st.session_state.data            = None
if "scores"           not in st.session_state: st.session_state.scores          = None
if "anomalies"        not in st.session_state: st.session_state.anomalies       = None
if "active_page"      not in st.session_state: st.session_state.active_page     = "Overview"
if "active_protocol"  not in st.session_state: st.session_state.active_protocol = None


def load_platform_data(force: bool = False):
    if force:
        get_cache().clear()

    st.info("Fetching on-chain data — cached for 24 hours after this first load.")
    bar    = st.progress(0.0)
    status = st.empty()

    def on_progress(fraction: float, label: str):
        bar.progress(min(fraction, 1.0))
        status.caption(label)

    try:
        data = load_all_data(status_cb=on_progress)
    except Exception as e:
        st.error(f"Data load failed: {e}")
        st.caption("Check your internet connection and try the Refresh button.")
        st.stop()

    from datetime import datetime, timedelta
    st.session_state.data      = data
    st.session_state.anomalies = detect_all_anomalies(data["tvl"])
    cutoff = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    anom_counts = {
        k: sum(
            1 for a in v
            if a["severity"] in ("high", "medium") and a["date"] >= cutoff
        )
        for k, v in st.session_state.anomalies.items()
    }
    st.session_state.scores    = score_all(data, anom_counts)
    st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────────
_PAGE_META = {
    "Overview":            "Risk scores & TVL heatmap for all protocols",
    "Protocol Deep Dive":  "Detailed metrics and history for one protocol",
    "Anomaly Feed":        "On-chain activity flagged as statistically unusual",
    "Stress Test":         "Simulate market shocks and measure resilience",
    "Portfolio Advisor":   "Position signals and allocation recommendations",
    "AI Risk Assistant":   "Chat interactively about the current risk landscape",
}

with st.sidebar:
    st.markdown(
        "<div style='font-size:20px;font-weight:700;color:#1e293b;margin-bottom:2px'>"
        "DeFi Risk Monitor</div>"
        "<div style='font-size:11px;color:#64748b'>Top-20 protocols · Live on-chain data</div>",
        unsafe_allow_html=True,
    )

    # Live risk summary strip (only when data is loaded)
    if st.session_state.scores:
        sc   = st.session_state.scores
        low  = sum(1 for v in sc.values() if v["composite"] < THRESHOLDS["low"])
        med  = sum(1 for v in sc.values() if THRESHOLDS["low"] <= v["composite"] < THRESHOLDS["medium"])
        high = sum(1 for v in sc.values() if v["composite"] >= THRESHOLDS["medium"])
        st.markdown(
            f"<div style='display:flex;gap:6px;margin:8px 0 4px'>"
            f"<span style='background:#dcfce7;color:#16a34a;padding:2px 8px;"
            f"border-radius:10px;font-size:11px'>✓ {low} Low</span>"
            f"<span style='background:#fef9c3;color:#d97706;padding:2px 8px;"
            f"border-radius:10px;font-size:11px'>⚠ {med} Med</span>"
            f"<span style='background:#fee2e2;color:#dc2626;padding:2px 8px;"
            f"border-radius:10px;font-size:11px'>✕ {high} High</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("<div style='font-size:11px;color:#64748b;margin-bottom:6px'>NAVIGATE</div>",
                unsafe_allow_html=True)

    for _pg, desc in _PAGE_META.items():
        if st.button(
            _pg,
            key=f"nav_{_pg}",
            use_container_width=True,
            help=desc,
        ):
            st.session_state.active_page = _pg
            st.rerun()

    st.divider()

    if st.session_state.scores:
        default_idx = 0
        names = list(st.session_state.scores.keys())
        if st.session_state.active_protocol in names:
            default_idx = names.index(st.session_state.active_protocol)
        protocol_select = st.selectbox(
            "Protocol (Deep Dive)",
            names,
            index=default_idx,
            help="Select a protocol to explore in the Deep Dive page",
        )
        st.session_state.active_protocol = protocol_select
    else:
        protocol_select = None

    st.divider()

    if st.button("Refresh Data", use_container_width=True,
                 help="Clear cache and re-fetch all data"):
        load_platform_data(force=True)

    if st.session_state.data:
        ts = st.session_state.data.get("fetched_at", "unknown")
        st.caption(f"Updated: {ts} UTC")


# ── Initial data load ──────────────────────────────────────────────────────────
if st.session_state.scores is None:
    load_platform_data()


# ── Route to page ──────────────────────────────────────────────────────────────
scores    = st.session_state.scores    or {}
anomalies = st.session_state.anomalies or {}
data      = st.session_state.data      or {}
page      = st.session_state.active_page

if not scores:
    st.warning("No data loaded. Click **Refresh Data** in the sidebar.")
    st.stop()

if page == "Overview":
    pg_overview.render(scores, anomalies, data.get("fear_greed", {}))

elif page == "Protocol Deep Dive":
    if protocol_select and scores:
        pg_detail.render(
            protocol_name = protocol_select,
            scores        = scores,
            tvl_data      = data.get("tvl", {}),
            anomalies     = anomalies,
        )
    else:
        st.info("Select a protocol in the sidebar to begin.")

elif page == "Anomaly Feed":
    pg_anomalies.render(anomalies, scores)

elif page == "Stress Test":
    pg_stress.render(scores)

elif page == "Portfolio Advisor":
    pg_portfolio.render(scores, anomalies)

elif page == "AI Risk Assistant":
    pg_chat.render(scores, anomalies, data)
