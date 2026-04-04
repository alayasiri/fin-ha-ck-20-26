"""
DeFi Risk Intelligence Platform
================================
Entry point — run with:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(
    page_title="DeFi Risk Intelligence",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Global CSS overrides — applied once on load
st.markdown("""
<style>
  /* Tighten default Streamlit padding */
  .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
  /* Metric card styling */
  [data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
  }
  [data-testid="metric-container"] label { color: #8b949e !important; font-size: 12px; }
  [data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #e6edf3 !important; font-size: 22px; font-weight: 700;
  }
  /* Sidebar */
  [data-testid="stSidebar"] { background: #0d1117; border-right: 1px solid #21262d; }
  /* Divider */
  hr { border-color: #21262d; margin: 0.6rem 0; }
  /* Selectbox */
  [data-testid="stSelectbox"] label { color: #8b949e; font-size: 12px; }
</style>
""", unsafe_allow_html=True)

from data.fetcher import load_all_data
from data.cache import get_cache
from models.risk_scorer import score_all
from models.anomaly_detector import detect_all_anomalies

import ui.overview as pg_overview
import ui.protocol_detail as pg_detail
import ui.anomalies as pg_anomalies
import ui.stress_test as pg_stress
import ui.portfolio as pg_portfolio


# ── Session state ──────────────────────────────────────────────────────────────
if "data" not in st.session_state:
    st.session_state.data    = None
if "scores" not in st.session_state:
    st.session_state.scores  = None
if "anomalies" not in st.session_state:
    st.session_state.anomalies = None


def load_platform_data(force: bool = False):
    if force:
        get_cache().clear()

    st.info("Fetching on-chain data — cached for 24 hours after this first load.")
    bar    = st.progress(0.0)
    status = st.empty()

    def on_progress(fraction: float, label: str):
        bar.progress(min(fraction, 1.0))
        status.caption(f"⟳  {label}")

    try:
        data = load_all_data(status_cb=on_progress)
    except Exception as e:
        st.error(f"Data load failed: {e}")
        st.caption("Check your internet connection and try the Refresh button.")
        st.stop()

    st.session_state.data      = data
    st.session_state.anomalies = detect_all_anomalies(data["tvl"])
    anom_counts                = {k: len(v) for k, v in st.session_state.anomalies.items()}
    st.session_state.scores    = score_all(data, anom_counts)
    st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<div style='font-size:20px;font-weight:700;color:#e6edf3;margin-bottom:4px'>"
        "⬡ DeFi Risk Monitor</div>",
        unsafe_allow_html=True,
    )
    st.caption("Top-20 protocols · Real-time data")
    st.divider()

    page = st.radio(
        "Navigate",
        ["Overview", "Protocol Deep Dive", "Anomaly Feed", "Stress Test", "Portfolio Advisor"],
        label_visibility="collapsed",
    )

    st.divider()

    if st.session_state.scores:
        protocol_select = st.selectbox(
            "Protocol (for deep dive)",
            list(st.session_state.scores.keys()),
        )
    else:
        protocol_select = None

    st.divider()

    if st.button("Refresh Data", use_container_width=True):
        load_platform_data(force=True)
        st.rerun()

    if st.session_state.data:
        ts = st.session_state.data.get("fetched_at", "unknown")
        st.caption(f"Last updated: {ts} UTC")


# ── Initial data load ──────────────────────────────────────────────────────────
if st.session_state.scores is None:
    load_platform_data()


# ── Route to page ──────────────────────────────────────────────────────────────
scores    = st.session_state.scores    or {}
anomalies = st.session_state.anomalies or {}
data      = st.session_state.data      or {}

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
        st.info("Select a protocol in the sidebar.")

elif page == "Anomaly Feed":
    pg_anomalies.render(anomalies, scores)

elif page == "Stress Test":
    pg_stress.render(scores)

elif page == "Portfolio Advisor":
    pg_portfolio.render(scores, anomalies)
