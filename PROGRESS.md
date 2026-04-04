# DeFi Risk Intelligence Platform — Progress Tracker

## Done

### Infrastructure
- [x] Project structure (`data/`, `models/`, `ui/`, `.streamlit/`)
- [x] `requirements.txt` (streamlit, plotly, pandas, numpy, scikit-learn, scipy, requests)
- [x] `.streamlit/config.toml` — dark theme, monospace font

### Data
- [x] `config.py` — metadata for 20 protocols (audit age, exploit history, bug bounty, governance, chain, CoinGecko ID)
- [x] `data/cache.py` — SQLite TTL cache (24-hour default), singleton pattern
- [x] `data/fetcher.py` — DeFiLlama TVL, CoinGecko prices (batch + per-protocol), Alternative.me Fear & Greed, GDELT news + keyword sentiment
- [x] Rate limiting enforced: DeFiLlama 1s, CoinGecko 2s (30 req/min free tier), GDELT 1s; sleeps fire only on live calls
- [x] Price histories fetched lazily (on Protocol Deep Dive page only, not at startup)
- [x] Threaded TVL + sentiment fetching with per-stage progress callbacks

### Models
- [x] `models/risk_scorer.py` — 5-component composite score (0–100):
  - Liquidity 25% (TVL drawdown, 7d/30d change)
  - Smart Contract 25% (audit age, exploit severity, bug bounty)
  - Governance 20% (token concentration, timelock, chain-specific flags)
  - Market 20% (price volatility, 30d return)
  - Sentiment 10% (Fear & Greed + news polarity)
- [x] Signal logic: INCREASE (<30) | HOLD (30–45) | REDUCE (45–65) | EXIT (>65)
- [x] `models/anomaly_detector.py` — rolling z-score (±2.5σ threshold) + Isolation Forest (5% contamination)
- [x] `models/stress_tester.py` — 4 interactive scenarios:
  - ETH Price Crash (param: % drop)
  - DeFi Liquidity Exodus (param: % outflow)
  - Stablecoin Depeg (param: depeg magnitude)
  - Smart Contract Exploit (param: target protocol + % drained)

### Dashboard (Streamlit)
- [x] `app.py` — entry point, session state, sidebar nav, initial data load with progress bar + `st.rerun()` after first load
- [x] **Overview** — 4 metric cards, Plotly treemap (size=TVL, color=risk), sortable HTML risk table, Fear & Greed sparkline
- [x] **Protocol Deep Dive** — gauge chart, component bar chart, TVL history with anomaly markers + peak line, lazy price chart, static risk factor table, anomaly event list
- [x] **Anomaly Feed** — severity filter, protocol filter, stacked bar chart, event feed with z-score histogram
- [x] **Stress Test** — scenario picker, parameter sliders, before/after score chart, TVL impact chart, full results table with threshold breach flags
- [x] **Portfolio Advisor** — signal summary cards, per-protocol signal rows with rationale + max allocation, position cap bar chart, risk correlation heatmap, key takeaways (exit/reduce/buy callouts)

---

## Known Issues Fixed
- [x] Blank screen on first load — was caused by `placeholder.container()` + threaded progress callbacks; fixed by flattening to direct `st.progress` + `st.rerun()` after load
- [x] Cache serialisation — numpy floats in market score converted to Python `float()` before JSON storage
- [x] Rate limits — CoinGecko corrected from 1.2s to 2.0s (30 req/min), GDELT from 0.5s to 1.0s; sleeps moved inside fetch functions so cache hits are instant

---

## Left To Do / Nice To Have

### Data & Model
- [ ] Add utilization rate for lending protocols (Aave, Compound) from on-chain subgraph or DeFiLlama yields endpoint
- [ ] Add governance activity signal (recent proposal count from Tally/Snapshot API — free)
- [ ] Improve sentiment: add token-specific keyword weighting vs generic DeFi terms
- [ ] Back-fill historical anomaly events with known incidents (Terra/LUNA, Curve hack, etc.) as reference markers

### Dashboard
- [ ] Export risk report as PDF / CSV from any page
- [ ] Real-time alert banner — highlight if any protocol score crossed a threshold since last load
- [ ] Protocol comparison view — overlay 2–3 protocols on the same TVL/score chart
- [ ] Portfolio input — let user enter actual holdings ($) and compute weighted portfolio risk score
- [ ] Mobile-friendly layout pass (sidebar collapse, smaller charts)

### Presentation / Demo
- [ ] Slide deck: risk framework, data sources, modelling approach, investment relevance
- [ ] Sample analysis write-up: one worked example of anomaly detection catching a real event
- [ ] Record a 2-minute screen demo video

---

## How to Run

```bash
cd /Users/vighaneshs/finhack2026
source venv/bin/activate
streamlit run app.py
```

First load fetches live data (~35s). All subsequent loads use the 24-hour cache.
Press **Refresh Data** in the sidebar to force a fresh fetch.
