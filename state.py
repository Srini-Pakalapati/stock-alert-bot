"""SQLite dedup store. Committed back to the repo by the GitHub Actions workflow
after every run so state survives across stateless runners."""
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import date

DB_PATH = "state.db"


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notified (key TEXT PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def was_notified(key: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM notified WHERE key = ?", (key,)).fetchone()
        return row is not None


def mark_notified(key: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO notified (key) VALUES (?)", (key,))


def headline_key(title: str, source: str) -> str:
    digest = hashlib.sha256(f"{source}:{title}".encode("utf-8")).hexdigest()[:16]
    return f"news:{digest}"


def price_move_key(ticker: str, pct_change: float, session: str) -> str:
    """Buckets moves in steps of 5% so a stock sitting at +7% doesn't re-fire every cycle,
    but a later jump to +12% does."""
    bucket = int(pct_change / 5) * 5
    return f"price:{ticker}:{date.today().isoformat()}:{session}:{bucket}"
