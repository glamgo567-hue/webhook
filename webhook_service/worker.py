import argparse
import logging
import sqlite3
import time
from typing import Callable

from . import db, taskqueue
from .handlers import Handler, SkipEvent, make_handler

log = logging.getLogger(__name__)


def process_one(conn: sqlite3.Connection, handler: Handler,
                clock: Callable[[], float] = time.time) -> bool:
    task = taskqueue.claim_next(conn, clock())
    if task is None:
        return False

    try:
        handler(task.event_type, task.payload)
    except SkipEvent as exc:
        log.info("Задача %s пропущена: %s", task.id, exc)
        stored = taskqueue.mark_done(conn, task, "skipped", clock())
    except Exception as exc:
        log.warning("Задача %s, попытка %s/%s: %s",
                    task.id, task.attempts, taskqueue.MAX_ATTEMPTS, exc)
        stored = taskqueue.mark_failed_attempt(conn, task, f"{type(exc).__name__}: {exc}", clock())
    else:
        stored = taskqueue.mark_done(conn, task, "success", clock())

    if not stored:
        log.warning("Задача %s: аренда истекла, результат не сохранён", task.id)
    return True


def run(db_path: str, handler: Handler, poll_interval: float = 0.5, once: bool = False) -> None:
    db.init_db(db_path)
    conn = db.connect(db_path)
    log.info("Воркер запущен, база %s", db_path)
    try:
        while True:
            processed = process_one(conn, handler)
            if once and not processed:
                return
            if not processed:
                time.sleep(poll_interval)
    except KeyboardInterrupt:
        log.info("Воркер остановлен")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Обработчик очереди событий")
    parser.add_argument("--db", default="events.db", help="путь к файлу SQLite")
    parser.add_argument("--fail-rate", type=float, default=0.3,
                        help="вероятность имитации сбоя, от 0 до 1")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--once", action="store_true",
                        help="обработать готовые задачи и выйти")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.db, make_handler(args.fail_rate), args.poll_interval, args.once)


if __name__ == "__main__":
    main()
