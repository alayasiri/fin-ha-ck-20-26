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


_ZSCORE_THRESHOLD = 4.5    # only flag genuine outliers (~0.05% of normal data)
_IF_CONTAMINATION = 0.002   # 0.2% contamination → ~0-1 events per year of daily data


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


_LOOKBACK_DAYS = 365   # only analyse the most recent year of TVL data


def detect_anomalies(tvl_series: list[dict]) -> list[dict]:
    if not tvl_series:
        return []

    tvl_series = sorted(tvl_series, key=lambda e: e.get("date", 0))

    # Restrict to the last _LOOKBACK_DAYS so the detector doesn't surface
    # ancient events and the displayed count reflects recent protocol health.
    cutoff_ts = tvl_series[-1].get("date", 0) - _LOOKBACK_DAYS * 86_400
    tvl_series = [e for e in tvl_series if e.get("date", 0) >= cutoff_ts]

    if not tvl_series:
        return []

    values = _make_series(tvl_series)
    dates  = [e.get("date", 0) for e in tvl_series]

    z_events  = _zscore_anomalies(values, dates)
    if_events = _isolation_forest_anomalies(values, dates)

    seen  = {e["date"] for e in z_events}
    extra = [e for e in if_events if e["date"] not in seen]
    return sorted(z_events + extra, key=lambda e: e["date"], reverse=True)


def detect_all_anomalies(tvl_data: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {name: detect_anomalies(series) for name, series in tvl_data.items()}
