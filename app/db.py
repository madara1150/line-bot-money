"""SQLite storage. One file at DATA_DIR/expenses.db."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    amount      REAL NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    merchant    TEXT,
    spent_at    TEXT NOT NULL,          -- ISO datetime, local time
    source      TEXT NOT NULL,          -- 'text' | 'slip'
    slip_ref    TEXT UNIQUE,            -- bank transaction ref, blocks duplicate slips
    raw         TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expenses_user_time ON expenses(user_id, spent_at);
"""


class DuplicateSlip(Exception):
    def __init__(self, existing: sqlite3.Row):
        super().__init__(f"slip already recorded as #{existing['id']}")
        self.existing = existing


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on error, always close."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def add_expense(
    user_id: str,
    amount: float,
    description: str,
    category: str,
    spent_at: datetime,
    source: str,
    merchant: str | None = None,
    slip_ref: str | None = None,
    raw: str | None = None,
) -> int:
    if category not in config.CATEGORIES:
        category = "อื่นๆ"
    with connect() as conn:
        if slip_ref:
            existing = conn.execute("SELECT * FROM expenses WHERE slip_ref = ?", (slip_ref,)).fetchone()
            if existing:
                raise DuplicateSlip(existing)
        cur = conn.execute(
            """INSERT INTO expenses
               (user_id, amount, description, category, merchant, spent_at, source, slip_ref, raw, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                round(float(amount), 2),
                description.strip() or "ไม่ระบุ",
                category,
                merchant,
                spent_at.isoformat(timespec="minutes"),
                source,
                slip_ref,
                raw,
                datetime.now(config.TZ).isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid


def delete(user_id: str, expense_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return row


def delete_last(user_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
    return delete(user_id, row["id"]) if row else None


def set_category(user_id: str, expense_id: int, category: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE expenses SET category = ? WHERE id = ? AND user_id = ?",
            (category, expense_id, user_id),
        )
        return cur.rowcount > 0


def get_many(user_id: str, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    with connect() as conn:
        return conn.execute(
            f"SELECT * FROM expenses WHERE user_id = ? AND id IN ({marks}) ORDER BY id",
            (user_id, *ids),
        ).fetchall()


def recent(user_id: str, limit: int = 10) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? ORDER BY spent_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


def between(user_id: str, start: datetime, end: datetime) -> list[sqlite3.Row]:
    """Rows with start <= spent_at < end."""
    with connect() as conn:
        return conn.execute(
            """SELECT * FROM expenses WHERE user_id = ? AND spent_at >= ? AND spent_at < ?
               ORDER BY spent_at, id""",
            (user_id, start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")),
        ).fetchall()
