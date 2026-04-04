"""
Two-layer anomaly detection on TVL time series:

  1. Rolling z-score  — flags single-day moves beyond ±2.5σ
  2. Isolation Forest — catches multivariate anomalies across
                        (level, 7d-change, 30d-change) simultaneously

Returns a list of anomaly events per protocol, each with a severity
label (low / medium / high) and a short human-readable description.
"""
import math
import statistics
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import IsolationForest


_ZSCORE_THRESHOLD = 2.5
_IF_CONTAMINATION = 0.05   # ~5% expected anomaly rate


def _make_series(tvl_entries: list[dict]) -> list[float]:
    return [e.get("totalLiquidityUSD", 0.0) for e in tvl_entries]


def _zscore_anomalies(values: list[float], dates: list[int]) -> list[dict]:
    if len(values) < 14:
        return []

    window = 30
    events = []
    for i in range(window, len(values)):
        window_vals = values[i - window : i]
        mean = statistics.mean(window_vals)
        std  = statistics.stdev(window_vals)
        if std < 1e-6:
            continue

        z = (values[i] - mean) / std
        if abs(z) < _ZSCORE_THRESHOLD:
            continue

        pct_change = (values[i] - values[i - 1]) / values[i - 1] * 100 if values[i - 1] else 0
        direction  = "dropped" if pct_change < 0 else "jumped"
        severity   = "high" if abs(z) > 4 else ("medium" if abs(z) > 3 else "low")

        ts = dates[i] if dates else 0
        events.append({
            "date":        datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "unknown",
            "type":        "tvl_spike",
            "description": f"TVL {direction} {abs(pct_change):.1f}% in 24h (z={z:.2f})",
            "severity":    severity,
            "z_score":     round(z, 3),
            "pct_change":  round(pct_change, 2),
            "tvl_usd":     values[i],
        })

    return events


def _isolation_forest_anomalies(values: list[float], dates: list[int]) -> list[dict]:
    if len(values) < 30:
        return []

    # Feature matrix: [log_tvl, 7d_change, 30d_change]
    rows = []
    for i in range(30, len(values)):
        ref7  = values[i - 7]  if values[i - 7]  > 0 else 1
        ref30 = values[i - 30] if values[i - 30] > 0 else 1
        rows.append([
            math.log(values[i] + 1),
            (values[i] - ref7)  / ref7,
            (values[i] - ref30) / ref30,
        ])

    X   = np.array(rows)
    clf = IsolationForest(contamination=_IF_CONTAMINATION, random_state=42, n_estimators=80)
    labels = clf.fit_predict(X)

    events = []
    for idx, lbl in enumerate(labels):
        if lbl != -1:
            continue
        i  = idx + 30
        ts = dates[i] if dates else 0
        score_val = clf.score_samples(X[idx : idx + 1])[0]
        events.append({
            "date":        datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "unknown",
            "type":        "multivariate_anomaly",
            "description": "Unusual combination of TVL level, 7d-trend, and 30d-trend",
            "severity":    "medium" if score_val > -0.15 else "high",
            "z_score":     round(score_val, 4),
            "pct_change":  0.0,
            "tvl_usd":     values[i],
        })

    return events


def detect_anomalies(tvl_series: list[dict]) -> list[dict]:
    if not tvl_series:
        return []

    # Sort chronologically — DeFiLlama usually returns ascending but not always
    tvl_series = sorted(tvl_series, key=lambda e: e.get("date", 0))
    values = _make_series(tvl_series)
    dates  = [e.get("date", 0) for e in tvl_series]

    z_events  = _zscore_anomalies(values, dates)
    if_events = _isolation_forest_anomalies(values, dates)

    # Deduplicate by date — prefer z-score events (more interpretable)
    seen  = {e["date"] for e in z_events}
    extra = [e for e in if_events if e["date"] not in seen]
    all_events = sorted(z_events + extra, key=lambda e: e["date"], reverse=True)

    return all_events[:20]   # cap to 20 most recent


def detect_all_anomalies(tvl_data: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {name: detect_anomalies(series) for name, series in tvl_data.items()}
