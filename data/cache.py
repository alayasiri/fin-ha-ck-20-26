import json
import os
import time
import threading
from pathlib import Path

# Load .env before reading env vars (dotenv may not be loaded yet at import time)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists(".env"):
        with open(".env") as _f:
            for _line in _f:
                if "=" in _line and not _line.strip().startswith("#"):
                    _k, _, _v = _line.strip().partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

_DB_PATH     = str(Path(__file__).parent / ".cache.db")
_TURSO_URL   = os.environ.get("TURSO_DATABASE_URL", "")
_TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")


def _open_connection():
    """Open a libsql (Turso) embedded replica if credentials are set, else local SQLite."""
    if _TURSO_URL and _TURSO_TOKEN:
        try:
            import libsql_experimental as libsql
            conn = libsql.connect(_DB_PATH, sync_url=_TURSO_URL, auth_token=_TURSO_TOKEN)
            conn.sync()
            return conn, True
        except Exception as e:
            print(f"[cache] Turso connection failed ({e}), falling back to local SQLite.")
    import sqlite3
    return sqlite3.connect(_DB_PATH, check_same_thread=False), False


class Cache:
    def __init__(self):
        self._lock = threading.Lock()
        self._db, self._turso = _open_connection()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS kv "
            "(key TEXT PRIMARY KEY, val TEXT, exp REAL)"
        )
        self._db.commit()
        if self._turso:
            self._db.sync()

    def _sync(self):
        if self._turso:
            try:
                self._db.sync()
            except Exception:
                pass

    def get(self, key: str):
        with self._lock:
            self._sync()
            row = self._db.execute(
                "SELECT val, exp FROM kv WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            val, exp = row
            if exp < time.time():
                self._db.execute("DELETE FROM kv WHERE key = ?", (key,))
                self._db.commit()
                if self._turso:
                    self._db.sync()
                return None
            return json.loads(val)

    def set(self, key: str, value, ttl: int = 86_400):
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time() + ttl),
            )
            self._db.commit()
            if self._turso:
                self._db.sync()

    def clear(self):
        with self._lock:
            self._db.execute("DELETE FROM kv")
            self._db.commit()
            if self._turso:
                self._db.sync()

    def keys(self) -> list[str]:
        with self._lock:
            self._sync()
            rows = self._db.execute(
                "SELECT key FROM kv WHERE exp > ?", (time.time(),)
            ).fetchall()
            return [r[0] for r in rows]


_instance: Cache | None = None


def get_cache() -> Cache:
    global _instance
    if _instance is None:
        _instance = Cache()
    return _instance
