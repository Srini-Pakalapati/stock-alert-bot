"""SQLite dedup store. Committed back to the repo by the GitHub Actions workflow
after every run so state survives across stateless runners."""
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import date

DB_PATH = "state.db"


@contextmanager
def _conn():
    """Open the SQLite connection, ensuring the `notified` table exists, and
    commit on clean exit. The file at DB_PATH is what gets git-committed back
    to the repo by the Actions workflow after each run."""
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
    """True if an alert with this dedup key has already been sent."""
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM notified WHERE key = ?", (key,)).fetchone()
        return row is not None


def mark_notified(key: str) -> None:
    """Record that an alert with this dedup key has been sent, so it isn't repeated."""
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO notified (key) VALUES (?)", (key,))


def headline_key(title: str, source: str) -> str:
    """Build a stable dedup key for a news headline from its title + source.

    Same (title, source) always hashes to the same key, so the same headline
    seen again on a later poll is recognized as already-handled.
    """
    digest = hashlib.sha256(f"{source}:{title}".encode("utf-8")).hexdigest()[:16]
    return f"news:{digest}"


def price_move_key(ticker: str, pct_change: float, session: str) -> str:
    """Buckets moves in steps of 5% so a stock sitting at +7% doesn't re-fire every cycle,
    but a later jump to +12% does."""
    bucket = int(pct_change / 5) * 5
    return f"price:{ticker}:{date.today().isoformat()}:{session}:{bucket}"
