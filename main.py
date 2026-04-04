import csv
import ssl
import time
import urllib.request
import urllib.error
import json
from dataclasses import dataclass

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

BASE_URL = "https://api.llama.fi"

# DeFiLlama slug overrides for protocols whose names differ from the API slug
SLUG_OVERRIDES = {
    "Sky (MakerDAO)": "makerdao",
    "1Inch": "1inch",
    "Curve Finance": "curve-dex",
    "Compound": "compound-v2",
    "Convex Finance": "convex-finance",
    "Frax Finance": "frax",
    "PancakeSwap": "pancakeswap",
    "Beefy Finance": "beefy",
    "Yearn Finance": "yearn-finance",
    "Kamino Finance": "kamino",
    "GMX": "gmx",
    "JustLend": "justlend",
    "Instadapp": "fluid-lending",  # Instadapp rebranded to Fluid
}


def protocol_slug(name: str) -> str:
    return SLUG_OVERRIDES.get(name, name.lower().replace(" ", "-"))


_RATE_LIMIT_DELAY = 1.0   # seconds between requests (free tier: standard limit)
_MAX_RETRIES = 3


def fetch_protocol_tvl(slug: str) -> list[dict]:
    """Fetch historical TVL entries [{date, totalLiquidityUSD}, ...] for a protocol.

    Respects DeFiLlama free-tier rate limits:
    - 1 s minimum between every call (_RATE_LIMIT_DELAY)
    - Obeys Retry-After header on 429
    - Exponential backoff for up to _MAX_RETRIES retries
    """
    url = f"{BASE_URL}/protocol/{slug}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})

    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
                data = json.loads(resp.read())
            return data.get("tvl", [])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = int(e.headers.get("Retry-After") or 2 ** (attempt + 1))
                print(f"    rate-limited on {slug}, waiting {retry_after}s…")
                time.sleep(retry_after)
            else:
                raise
        except urllib.error.URLError:
            if attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(2 ** (attempt + 1))

    raise RuntimeError(f"Failed to fetch {slug} after {_MAX_RETRIES} retries")


@dataclass
class ProtocolTracker:
    name: str
    category: str
    chain: str
    max_tvl: float = 0.0
    current_tvl: float = 0.0

    @property
    def drawdown(self) -> float:
        """Drawdown as a fraction (0.0–1.0). Positive means TVL has fallen from peak."""
        if self.max_tvl == 0:
            return 0.0
        return (self.max_tvl - self.current_tvl) / self.max_tvl

    @property
    def drawdown_pct(self) -> float:
        return self.drawdown * 100

    def ingest(self, tvl_series: list[dict]) -> None:
        """Feed sorted historical TVL entries and update max/current."""
        for entry in tvl_series:
            tvl = entry.get("totalLiquidityUSD", 0.0)
            if tvl > self.max_tvl:
                self.max_tvl = tvl
        if tvl_series:
            self.current_tvl = tvl_series[-1].get("totalLiquidityUSD", 0.0)

    def __str__(self) -> str:
        return (
            f"{self.name:<20} | "
            f"Current: ${self.current_tvl:>14,.0f} | "
            f"Peak:    ${self.max_tvl:>14,.0f} | "
            f"Drawdown: {self.drawdown_pct:>6.1f}%"
        )


def load_protocols(csv_path: str) -> list[ProtocolTracker]:
    trackers = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            trackers.append(ProtocolTracker(
                name=row["Protocol"],
                category=row["Category"],
                chain=row["Main Chain"],
            ))
    return trackers


ALERT_THRESHOLD = 20.0  # percent


if __name__ == "__main__":
    trackers = load_protocols("protocols.csv")

    print(f"Fetching historical TVL from DefiLlama for {len(trackers)} protocols...\n")

    alerts = []
    errors = []

    for tracker in trackers:
        slug = protocol_slug(tracker.name)
        try:
            tvl_series = fetch_protocol_tvl(slug)
            tracker.ingest(tvl_series)
            print(tracker)
            if tracker.drawdown_pct >= ALERT_THRESHOLD:
                alerts.append(tracker)
        except Exception as e:
            errors.append((tracker.name, str(e)))
            print(f"  !! {tracker.name}: failed to fetch ({e})")
        time.sleep(_RATE_LIMIT_DELAY)

    if alerts:
        print(f"\n{'='*70}")
        print(f"DRAWDOWN ALERTS (>= {ALERT_THRESHOLD}% from peak)")
        print(f"{'='*70}")
        for t in alerts:
            print(f"  {t.name}: {t.drawdown_pct:.1f}% drawdown  "
                  f"(peak ${t.max_tvl:,.0f} → current ${t.current_tvl:,.0f})")

    if errors:
        print(f"\nFailed to fetch: {', '.join(n for n, _ in errors)}")
