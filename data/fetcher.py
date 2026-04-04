"""
Fetches data from:
  - DeFiLlama (TVL history, free, no key)
  - CoinGecko  (prices + 30d OHLC, free tier)
  - Alternative.me (Fear & Greed Index, free, no key)
  - GDELT      (news headlines, free, no key) + Qwen LLM sentiment (Ollama, local)

Free-tier rate limits enforced:
  DeFiLlama   — 1.0s between calls (no published limit; conservative)
  CoinGecko   — 2.0s between calls (30 req/min on the public endpoint)
  GDELT       — 1.0s between calls (recommended by GDELT docs)
  Alternative.me — single call per session; no constraint needed

Sleeps only fire when a live network request is made.
Cached responses return immediately.
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock

from config import LENDING_POOL_SLUGS, PROTOCOLS, SLUG_OVERRIDES, SNAPSHOT_SPACES
from data.cache import get_cache

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

LLAMA_BASE    = "https://api.llama.fi"
GECKO_BASE    = "https://api.coingecko.com/api/v3"
FNG_URL       = "https://api.alternative.me/fng/?limit=7"
GDELT_BASE    = "https://api.gdeltproject.org/api/v2/doc/doc"
_OLLAMA_URL   = os.environ.get("OLLAMA_URL",   "http://localhost:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")


def _get(url: str, timeout: int = 15) -> dict | list:
    req = urllib.request.Request(url, headers={
        "Accept":     "application/json",
        "User-Agent": "defi-risk-platform/1.0",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 2 ** (attempt + 2))
                time.sleep(wait)
            elif e.code in (404, 400):
                return {}
            else:
                raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


def _slug(name: str) -> str:
    return SLUG_OVERRIDES.get(name, name.lower().replace(" ", "-"))


# ── TVL ────────────────────────────────────────────────────────────────────────

_llama_lock = Lock()   # one live DeFiLlama request at a time (shared socket pool)


def fetch_tvl_history(protocol_name: str) -> list[dict]:
    cache_key = f"tvl:{protocol_name}"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with _llama_lock:
        slug   = _slug(protocol_name)
        data   = _get(f"{LLAMA_BASE}/protocol/{slug}")
        series = data.get("tvl", []) if isinstance(data, dict) else []
        cache.set(cache_key, series, ttl=86_400)
        time.sleep(0.3)   # brief courtesy gap between live calls
    return series


def fetch_all_tvl(status_cb=None) -> dict[str, list[dict]]:
    names     = list(PROTOCOLS.keys())
    result    = {}
    completed = 0
    lock      = Lock()

    def _fetch(name):
        return name, fetch_tvl_history(name)

    # DeFiLlama has no rate limit — parallelise across protocols.
    # _llama_lock inside fetch_tvl_history keeps live calls sequential
    # while still letting cached calls return instantly in parallel.
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch, n): n for n in names}
        for fut in as_completed(futures):
            name, series = fut.result()
            result[name] = series
            with lock:
                completed += 1
                if status_cb:
                    status_cb(completed / len(names), f"TVL: {name}")

    return result


# ── Prices ────────────────────────────────────────────────────────────────────

def fetch_prices() -> dict[str, dict]:
    cache_key = "prices:batch"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    ids = ",".join({m["coingecko_id"] for m in PROTOCOLS.values()})
    url = (
        f"{GECKO_BASE}/simple/price"
        f"?ids={ids}&vs_currencies=usd"
        f"&include_24hr_change=true&include_market_cap=true"
    )
    try:
        raw = _get(url)
    except Exception:
        raw = {}

    # Remap from coingecko_id → protocol_name for convenience
    id_to_name = {m["coingecko_id"]: n for n, m in PROTOCOLS.items()}
    out = {}
    for cg_id, vals in raw.items():
        name = id_to_name.get(cg_id, cg_id)
        out[name] = {
            "price_usd":      vals.get("usd", 0.0),
            "change_24h_pct": vals.get("usd_24h_change", 0.0),
            "market_cap_usd": vals.get("usd_market_cap", 0.0),
        }

    cache.set(cache_key, out, ttl=86_400)
    time.sleep(2.0)   # CoinGecko: 30 req/min on free tier = 2s minimum
    return out


def fetch_price_history(protocol_name: str) -> list[float]:
    cache_key = f"px_hist:{protocol_name}"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    cg_id = PROTOCOLS[protocol_name]["coingecko_id"]
    url = f"{GECKO_BASE}/coins/{cg_id}/market_chart?vs_currency=usd&days=30&interval=daily"
    try:
        data  = _get(url)
        prices = [p[1] for p in data.get("prices", [])]
    except Exception:
        prices = []

    cache.set(cache_key, prices, ttl=86_400)
    time.sleep(2.0)   # CoinGecko: 30 req/min on free tier = 2s minimum
    return prices


def fetch_all_price_histories() -> dict[str, list[float]]:
    cache_key = "px_hist:all"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    out = {}
    for name in PROTOCOLS:
        out[name] = fetch_price_history(name)

    cache.set(cache_key, out, ttl=86_400)
    return out


# ── Utilization rate (lending protocols) ─────────────────────────────────────

def fetch_utilization_rates() -> dict[str, float]:
    """Returns borrow utilization (0–1) for lending protocols via DeFiLlama /pools."""
    cache_key = "utilization"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    out = {}
    try:
        pools = _get(f"{LLAMA_BASE.replace('api.llama.fi','yields.llama.fi')}/pools")
        if not isinstance(pools, dict):
            return {}
        for pool in pools.get("data", []):
            project = pool.get("project", "")
            for name, slug in LENDING_POOL_SLUGS.items():
                if project == slug and pool.get("utilization") is not None:
                    # Average across pools of the same protocol
                    prev = out.get(name)
                    u = float(pool["utilization"])
                    out[name] = (prev + u) / 2 if prev is not None else u
    except Exception:
        pass

    cache.set(cache_key, out, ttl=86_400)
    return out


# ── Governance activity (Snapshot) ────────────────────────────────────────────

_SNAPSHOT_GQL = "https://hub.snapshot.org/graphql"


def fetch_governance_activity() -> dict[str, int]:
    """Returns number of governance proposals in the last 30 days per protocol."""
    cache_key = "governance_activity"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    import time as _time
    cutoff = int(_time.time()) - 30 * 86_400
    out    = {}

    for name, space in SNAPSHOT_SPACES.items():
        query = (
            '{"query":"{ proposals(first:50, where:{space:\\\"'
            + space
            + '\\\",created_gte:'
            + str(cutoff)
            + '}) { id } }"}'
        )
        req = urllib.request.Request(
            _SNAPSHOT_GQL,
            data=query.encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10, context=_SSL) as r:
                data = json.loads(r.read())
            proposals = data.get("data", {}).get("proposals", [])
            out[name] = len(proposals)
        except Exception:
            out[name] = 0
        time.sleep(0.5)

    cache.set(cache_key, out, ttl=86_400)
    return out


# ── BTC / ETH market context ──────────────────────────────────────────────────

def fetch_market_context() -> dict:
    """Fetch BTC and ETH price, 24h change, and 30d volatility.
    Used as macro regime signals in the risk scorer — separate from protocol
    token prices because BTC/ETH moves drive DeFi TVL regardless of whether
    a protocol's own token has repriced yet."""
    cache = get_cache()
    cached = cache.get("market_context")
    if cached is not None:
        return cached

    out = {"btc": {}, "eth": {}}
    try:
        url = (
            f"{GECKO_BASE}/simple/price"
            "?ids=bitcoin,ethereum&vs_currencies=usd"
            "&include_24hr_change=true&include_24hr_vol=true"
        )
        raw = _get(url)
        time.sleep(2.0)
        for cg_id, key in [("bitcoin", "btc"), ("ethereum", "eth")]:
            d = raw.get(cg_id, {}) if isinstance(raw, dict) else {}
            out[key] = {
                "price_usd":    d.get("usd", 0.0),
                "change_24h":   d.get("usd_24h_change", 0.0),
            }
    except Exception:
        pass

    # Fetch 30d price history for volatility
    for cg_id, key in [("bitcoin", "btc"), ("ethereum", "eth")]:
        try:
            url = (
                f"{GECKO_BASE}/coins/{cg_id}/market_chart"
                "?vs_currency=usd&days=30&interval=daily"
            )
            data   = _get(url)
            prices = [p[1] for p in (data.get("prices", []) if isinstance(data, dict) else [])]
            if len(prices) > 2:
                import numpy as _np
                rets = _np.diff(_np.log(_np.array(prices) + 1e-9))
                out[key]["vol_30d"] = round(float(_np.std(rets)) * 100, 3)
            time.sleep(2.0)
        except Exception:
            out[key]["vol_30d"] = 0.0

    cache.set("market_context", out, ttl=86_400)
    return out


# ── Fear & Greed ──────────────────────────────────────────────────────────────

def fetch_fear_greed() -> dict:
    cache = get_cache()
    cached = cache.get("fng")
    if cached is not None:
        return cached

    try:
        raw = _get(FNG_URL)
        entries = raw.get("data", [])
        current = entries[0] if entries else {}
        out = {
            "value":     int(current.get("value", 50)),
            "label":     current.get("value_classification", "Neutral"),
            "history":   [int(e["value"]) for e in entries],
        }
    except Exception:
        out = {"value": 50, "label": "Neutral", "history": [50]}

    cache.set("fng", out, ttl=86_400)
    return out


# ── News sentiment ─────────────────────────────────────────────────────────────

def _gdelt_headlines(query: str, days: int = 7) -> list[str]:
    params = urllib.parse.urlencode({
        "query":      f"{query} DeFi",
        "mode":       "artlist",
        "maxrecords": "15",
        "timespan":   f"{days}d",
        "format":     "json",
    })
    try:
        data = _get(f"{GDELT_BASE}?{params}", timeout=10)
        articles = data.get("articles", []) if isinstance(data, dict) else []
        return [a.get("title", "") for a in articles if a.get("title")]
    except Exception:
        return []


_POS = frozenset({
    "record", "launch", "upgrade", "partnership", "growth", "milestone",
    "integration", "adoption", "secure", "audit", "expansion", "surge",
    "soar", "strong", "bullish", "recover", "unlock", "approved", "live",
})
_NEG = frozenset({
    "hack", "exploit", "attack", "rug", "scam", "crash", "breach",
    "vulnerability", "drain", "loss", "freeze", "shutdown", "lawsuit",
    "fraud", "liquidation", "depeg", "insolvency", "suspended", "halted",
    "risk", "warning", "concern", "fell", "drop", "plunge", "slump",
})


def _score_headlines_llm(headlines: list[str]) -> float | None:
    """Send headlines to a locally-running Ollama model.
    Returns a float in [-1, 1] or None if Ollama is unavailable."""
    if not headlines:
        return 0.0

    bullet_list = "\n".join(f"- {h}" for h in headlines)
    prompt = (
        "You are a DeFi risk analyst. Given the news headlines below, "
        "return a single JSON object with one key 'score' — a float from "
        "-1.0 (very bearish / high risk) to 1.0 (very bullish / low risk). "
        "Consider hacks, exploits, and regulatory actions as strongly negative. "
        "Protocol launches, audits, and TVL growth as positive. "
        "Return ONLY the JSON, no explanation.\n\n"
        f"Headlines:\n{bullet_list}"
    )
    payload = json.dumps({
        "model":   _OLLAMA_MODEL,
        "prompt":  prompt,
        "stream":  False,
        "format":  "json",
        "options": {"temperature": 0.0},
    }).encode()

    try:
        req = urllib.request.Request(
            f"{_OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp   = json.loads(r.read())
            parsed = json.loads(resp.get("response", "{}"))
            score  = float(parsed.get("score", 0.0))
            return max(-1.0, min(1.0, score))
    except Exception:
        return None


def _score_headlines(headlines: list[str]) -> float:
    """LLM scoring via Ollama with keyword fallback if Ollama is unavailable."""
    llm_score = _score_headlines_llm(headlines)
    if llm_score is not None:
        return llm_score

    # Keyword fallback
    if not headlines:
        return 0.0
    total = 0.0
    for h in headlines:
        words = h.lower().split()
        pos = sum(1 for w in words if w.strip(".,!?") in _POS)
        neg = sum(1 for w in words if w.strip(".,!?") in _NEG)
        if pos + neg:
            total += (pos - neg) / (pos + neg)
    return round(total / len(headlines), 4)


def fetch_news_sentiment(protocol_name: str) -> float:
    """Returns sentiment in [-1, 1]. Negative = bearish, positive = bullish."""
    cache_key = f"sentiment:{protocol_name}"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    with _gdelt_lock:
        token     = PROTOCOLS[protocol_name]["token"]
        headlines = _gdelt_headlines(token)
        score     = _score_headlines(headlines)
        cache.set(cache_key, score, ttl=86_400)
        time.sleep(1.0)   # GDELT: 1s between live calls (recommended)
    return score


_gdelt_lock = Lock()   # GDELT recommends 1 req/s; serialise live calls


def fetch_all_sentiments(status_cb=None) -> dict[str, float]:
    cache_key = "sentiment:all"
    cache = get_cache()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    names     = list(PROTOCOLS.keys())
    out       = {}
    completed = 0
    cb_lock   = Lock()

    def _fetch(name):
        return name, fetch_news_sentiment(name)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch, n): n for n in names}
        for fut in as_completed(futures):
            name, score = fut.result()
            out[name] = score
            with cb_lock:
                completed += 1
                if status_cb:
                    status_cb(completed / len(names), f"Sentiment: {name}")

    cache.set(cache_key, out, ttl=86_400)
    return out


# ── Convenience: load everything at once ──────────────────────────────────────
# Price histories (CoinGecko, 20 calls × 2s) are NOT fetched here — they are
# loaded on demand in the Protocol Deep Dive page to keep startup time short.

def load_all_data(status_cb=None) -> dict:
    names = list(PROTOCOLS.keys())
    n     = len(names)

    # Stage 1 — TVL history (0 → 50%), parallelised
    def _tvl_cb(frac, label):
        if status_cb:
            status_cb(frac * 0.50, label)

    tvl_data = fetch_all_tvl(status_cb=_tvl_cb)

    # Stage 2 — Prices + Fear & Greed + BTC/ETH macro (50% → 62%)
    if status_cb:
        status_cb(0.50, "Token prices…")
    prices = fetch_prices()

    if status_cb:
        status_cb(0.54, "BTC / ETH market context…")
    market_context = fetch_market_context()

    if status_cb:
        status_cb(0.58, "Fear & Greed index…")
    fng = fetch_fear_greed()

    # Stage 3 — Utilization + governance (60% → 70%)
    if status_cb:
        status_cb(0.60, "Lending utilization rates…")
    utilization = fetch_utilization_rates()

    if status_cb:
        status_cb(0.65, "Governance activity (Snapshot)…")
    governance  = fetch_governance_activity()

    # Stage 4 — News sentiment (70% → 100%)
    def _sent_cb(frac, label):
        if status_cb:
            status_cb(0.70 + frac * 0.30, label)

    sentiments = fetch_all_sentiments(status_cb=_sent_cb)

    if status_cb:
        status_cb(1.0, "Done")

    return {
        "tvl":            tvl_data,
        "prices":         prices,
        "px_hist":        {},   # populated lazily per-protocol in Deep Dive
        "fear_greed":     fng,
        "sentiment":      sentiments,
        "utilization":    utilization,
        "governance":     governance,
        "market_context": market_context,
        "fetched_at":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
