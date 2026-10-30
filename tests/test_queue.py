import json

from webhook_service import db, taskqueue
from webhook_service.handlers import make_handler
from webhook_service.worker import process_one


def add_event(conn, clock, event_id="e1", event_type="payment_succeeded"):
    db.save_event(conn, event_id, event_type, json.dumps({"order_id": 1}), now=clock())


def task_row(conn, event_id="e1"):
    return conn.execute("SELECT * FROM tasks WHERE event_id = ?", (event_id,)).fetchone()


def always_fail(event_type, payload):
    raise RuntimeError("внешний сервис недоступен")


def test_successful_processing(conn, clock):
    add_event(conn, clock)

    assert process_one(conn, make_handler(fail_rate=0), clock) is True

    row = task_row(conn)
    assert (row["status"], row["attempts"]) == ("success", 1)
    assert row["locked_until"] is None


def test_unknown_event_type_is_skipped(conn, clock):
    add_event(conn, clock, event_type="something_new")

    process_one(conn, make_handler(fail_rate=0), clock)

    assert task_row(conn)["status"] == "skipped"


def test_retries_with_growing_delay_then_failed(conn, clock):
    add_event(conn, clock)

    process_one(conn, always_fail, clock)
    row = task_row(conn)
    assert (row["status"], row["attempts"]) == ("pending", 1)
    assert row["next_run_at"] == clock() + taskqueue.backoff_delay(1)

    assert process_one(conn, always_fail, clock) is False

    clock.advance(taskqueue.backoff_delay(1))
    process_one(conn, always_fail, clock)
    row = task_row(conn)
    assert (row["status"], row["attempts"]) == ("pending", 2)
    assert row["next_run_at"] == clock() + taskqueue.backoff_delay(2)
    assert taskqueue.backoff_delay(2) > taskqueue.backoff_delay(1)

    clock.advance(taskqueue.backoff_delay(2))
    process_one(conn, always_fail, clock)
    row = task_row(conn)
    assert (row["status"], row["attempts"]) == ("failed", 3)
    assert "внешний сервис недоступен" in row["last_error"]

    clock.advance(3600)
    assert process_one(conn, always_fail, clock) is False


def test_flaky_handler_succeeds_on_retry(conn, clock):
    add_event(conn, clock)
    results = iter([0.0, 1.0])
    handler = make_handler(fail_rate=0.5, rng=lambda: next(results))

    process_one(conn, handler, clock)
    clock.advance(taskqueue.backoff_delay(1))
    process_one(conn, handler, clock)

    row = task_row(conn)
    assert (row["status"], row["attempts"]) == ("success", 2)


def test_task_of_crashed_worker_does_not_stay_pending(conn, clock):
    add_event(conn, clock)

    for _ in range(taskqueue.MAX_ATTEMPTS):
        assert taskqueue.claim_next(conn, clock()) is not None
        assert taskqueue.claim_next(conn, clock()) is None
        clock.advance(taskqueue.LEASE_SECONDS)

    assert taskqueue.claim_next(conn, clock()) is None
    row = task_row(conn)
    assert row["status"] == "failed"
    assert "Аренда истекла" in row["last_error"]


def test_late_worker_cannot_overwrite_result(conn, clock):
    add_event(conn, clock)
    stale = taskqueue.claim_next(conn, clock())
    clock.advance(taskqueue.LEASE_SECONDS)
    fresh = taskqueue.claim_next(conn, clock())

    assert taskqueue.mark_done(conn, fresh, "success", clock()) is True
    assert taskqueue.mark_failed_attempt(conn, stale, "опоздал", clock()) is False
    assert task_row(conn)["status"] == "success"
