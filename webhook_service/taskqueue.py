import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0
LEASE_SECONDS = 30.0


@dataclass(frozen=True)
class Task:
    id: int
    event_id: str
    event_type: str
    payload: dict[str, Any]
    attempts: int
    lock_token: str


def backoff_delay(attempt: int) -> float:
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)


def claim_next(conn: sqlite3.Connection, now: float) -> Task | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        _fail_exhausted(conn, now)
        row = conn.execute(
            """
            SELECT t.id, t.event_id, t.attempts, e.type, e.payload
            FROM tasks t JOIN events e ON e.event_id = t.event_id
            WHERE t.status = 'pending'
              AND t.attempts < ?
              AND t.next_run_at <= ?
              AND (t.locked_until IS NULL OR t.locked_until <= ?)
            ORDER BY t.next_run_at, t.id
            LIMIT 1
            """,
            (MAX_ATTEMPTS, now, now),
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None

        token = uuid.uuid4().hex
        attempts = row["attempts"] + 1
        conn.execute(
            "UPDATE tasks SET attempts = ?, locked_until = ?, lock_token = ?, updated_at = ? "
            "WHERE id = ?",
            (attempts, now + LEASE_SECONDS, token, now, row["id"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return Task(
        id=row["id"],
        event_id=row["event_id"],
        event_type=row["type"],
        payload=json.loads(row["payload"]),
        attempts=attempts,
        lock_token=token,
    )


def mark_done(conn: sqlite3.Connection, task: Task, status: str, now: float) -> bool:
    if status not in ("success", "skipped"):
        raise ValueError(f"Недопустимый финальный статус: {status}")
    return _finish(conn, task, status=status, next_run_at=None, error=None, now=now)


def mark_failed_attempt(conn: sqlite3.Connection, task: Task, error: str, now: float) -> bool:
    if task.attempts >= MAX_ATTEMPTS:
        return _finish(conn, task, status="failed", next_run_at=None, error=error, now=now)
    return _finish(
        conn, task, status="pending",
        next_run_at=now + backoff_delay(task.attempts), error=error, now=now,
    )


def _finish(conn, task: Task, status: str, next_run_at: float | None,
            error: str | None, now: float) -> bool:
    cur = conn.execute(
        """
        UPDATE tasks
        SET status = ?,
            next_run_at = COALESCE(?, next_run_at),
            last_error = COALESCE(?, last_error),
            locked_until = NULL,
            lock_token = NULL,
            updated_at = ?
        WHERE id = ? AND lock_token = ?
        """,
        (status, next_run_at, error, now, task.id, task.lock_token),
    )
    return cur.rowcount == 1


def _fail_exhausted(conn, now: float) -> None:
    conn.execute(
        """
        UPDATE tasks
        SET status = 'failed',
            last_error = 'Аренда истекла на последней попытке (воркер не завершил обработку)',
            locked_until = NULL,
            lock_token = NULL,
            updated_at = ?
        WHERE status = 'pending'
          AND attempts >= ?
          AND (locked_until IS NULL OR locked_until <= ?)
        """,
        (now, MAX_ATTEMPTS, now),
    )
