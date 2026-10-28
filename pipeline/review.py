"""Step 11a: the review queue. Every item the pipeline can't settle on its own lands here, in one list
a person works through, highest priority first. Stored in SQLite (a database in a single file).

Three rules:
- Re-running the pipeline never creates duplicates: each problem has a stable key.
- A person's decision is final: once resolved, the same problem is not reopened by a re-run.
- A problem that disappears (the money arrived, a 'due soon' became 'unpaid') is closed by the system,
  with a note saying so. Only items still open are touched."""
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "review.db"

# How urgent each kind of problem is (bigger = sooner). Money already missing beats money arriving soon.
# Kinds are 10 apart and the size bonus is at most +9, so size can reorder items within a kind, never across.
WEIGHT = {"unpaid": 60, "partial": 50, "overpaid": 40, "unmatched": 40,
          "extraction": 30, "validation": 30, "late": 20, "due_soon": 10}

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY,
    key         TEXT UNIQUE NOT NULL,   -- what makes a problem 'the same problem' across runs
    kind        TEXT NOT NULL,          -- unpaid, partial, late, due_soon, unmatched, extraction, ...
    fund_id     TEXT,
    doc_id      TEXT,
    amount      TEXT,                   -- Decimal stored as text: exact
    detail      TEXT NOT NULL,
    priority    INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution  TEXT
)"""


@dataclass
class ReviewItem:
    id: int
    kind: str
    fund_id: str | None
    doc_id: str | None
    amount: Decimal | None
    detail: str
    priority: int
    status: str
    resolution: str | None = None


def priority(kind: str, amount: Decimal | None) -> int:
    """Kind first, then size: +1 per $100,000 at stake, capped at +9 (see WEIGHT)."""
    size = min(int((amount or 0) / 100_000), 9)
    return WEIGHT.get(kind, 30) + size


class ReviewQueue:
    def __init__(self, path: str | Path = DB):
        self.db = sqlite3.connect(path)
        self.db.execute(SCHEMA)

    def add(self, key: str, kind: str, detail: str, fund_id: str | None = None,
            doc_id: str | None = None, amount: Decimal | None = None) -> bool:
        """Add a problem. Returns False if it's already in the queue (open OR resolved)."""
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO items (key, kind, fund_id, doc_id, amount, detail, priority, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key, kind, fund_id, doc_id, None if amount is None else str(amount), detail,
             priority(kind, amount), datetime.now().isoformat(timespec="seconds")))
        self.db.commit()
        return cursor.rowcount == 1

    def open_items(self) -> list[ReviewItem]:
        rows = self.db.execute(
            "SELECT id, kind, fund_id, doc_id, amount, detail, priority, status, resolution FROM items "
            "WHERE status = 'open' ORDER BY priority DESC, id").fetchall()
        return [ReviewItem(r[0], r[1], r[2], r[3], Decimal(r[4]) if r[4] else None, *r[5:]) for r in rows]

    def resolve(self, item_id: int, resolution: str, by: str) -> None:
        if not resolution.strip():
            raise ValueError("say what was decided: a resolution note is required")
        self.db.execute("UPDATE items SET status = 'resolved', resolution = ?, resolved_by = ?, resolved_at = ? "
                        "WHERE id = ? AND status = 'open'",
                        (resolution, by, datetime.now().isoformat(timespec="seconds"), item_id))
        self.db.commit()

    def close_missing(self, keys_seen: set[str], as_of: str) -> int:
        """Close open items whose problem wasn't found in today's run. Returns how many."""
        open_keys = [k for (k,) in self.db.execute("SELECT key FROM items WHERE status = 'open'")]
        gone = [k for k in open_keys if k not in keys_seen]
        self.db.executemany(
            "UPDATE items SET status = 'resolved', resolved_by = 'system', resolved_at = ?, "
            "resolution = ? WHERE key = ? AND status = 'open'",
            [(datetime.now().isoformat(timespec="seconds"), f"no longer present in the {as_of} run", k)
             for k in gone])
        self.db.commit()
        return len(gone)

    def history(self) -> list[tuple]:
        return self.db.execute("SELECT key, kind, status, resolved_by, resolution FROM items ORDER BY id").fetchall()