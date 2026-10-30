import sqlite3
import time

TASK_STATUSES = ("pending", "success", "failed", "skipped")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT    NOT NULL UNIQUE,
    type        TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    received_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT    NOT NULL UNIQUE REFERENCES events(event_id),
    status       TEXT    NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'success', 'failed', 'skipped')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    next_run_at  REAL    NOT NULL,
    locked_until REAL,
    lock_token   TEXT,
    last_error   TEXT,
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_ready ON tasks (status, next_run_at);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(path: str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def save_event(conn: sqlite3.Connection, event_id: str, event_type: str,
               payload: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO events (event_id, type, payload, received_at) "
            "VALUES (?, ?, ?, ?)",
            (event_id, event_type, payload, now),
        )
        created = cur.rowcount == 1
        if created:
            conn.execute(
                "INSERT INTO tasks (event_id, next_run_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (event_id, now, now, now),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return created


def get_stats(conn: sqlite3.Connection) -> dict:
    events = {
        row["type"]: row["cnt"]
        for row in conn.execute(
            "SELECT type, COUNT(*) AS cnt FROM events GROUP BY type ORDER BY type"
        )
    }
    tasks = dict.fromkeys(TASK_STATUSES, 0)
    for row in conn.execute("SELECT status, COUNT(*) AS cnt FROM tasks GROUP BY status"):
        tasks[row["status"]] = row["cnt"]
    return {"events": events, "tasks": tasks}
