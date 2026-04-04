import json
import sqlite3
import time
import threading
from pathlib import Path

_DB = Path(__file__).parent / ".cache.db"


class Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(_DB, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS kv "
            "(key TEXT PRIMARY KEY, val TEXT, exp REAL)"
        )
        self._db.commit()

    def get(self, key: str):
        with self._lock:
            row = self._db.execute(
                "SELECT val, exp FROM kv WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            val, exp = row
            if exp < time.time():
                self._db.execute("DELETE FROM kv WHERE key = ?", (key,))
                self._db.commit()
                return None
            return json.loads(val)

    def set(self, key: str, value, ttl: int = 86_400):  # 24 hours default
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time() + ttl),
            )
            self._db.commit()

    def clear(self):
        with self._lock:
            self._db.execute("DELETE FROM kv")
            self._db.commit()

    def keys(self) -> list[str]:
        with self._lock:
            rows = self._db.execute("SELECT key FROM kv WHERE exp > ?", (time.time(),)).fetchall()
            return [r[0] for r in rows]


_instance: Cache | None = None


def get_cache() -> Cache:
    global _instance
    if _instance is None:
        _instance = Cache()
    return _instance
