import pytest


def make_event(event_id="abc-123", event_type="payment_succeeded", payload=None):
    return {"event_id": event_id, "type": event_type, "payload": payload or {"order_id": 1}}


def test_new_event_is_accepted_and_queued(client, conn):
    resp = client.post("/webhook", json=make_event())

    assert resp.status_code == 202
    assert resp.get_json() == {"event_id": "abc-123", "status": "accepted"}
    task = conn.execute("SELECT status, attempts FROM tasks WHERE event_id = 'abc-123'").fetchone()
    assert (task["status"], task["attempts"]) == ("pending", 0)


def test_duplicate_event_id_does_not_create_second_record(client, conn):
    first = client.post("/webhook", json=make_event())
    second = client.post("/webhook", json=make_event(payload={"order_id": 999}))

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.get_json()["status"] == "duplicate"
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    payload = conn.execute("SELECT payload FROM events").fetchone()[0]
    assert '"order_id": 1' in payload


def test_not_json_body_returns_400(client):
    resp = client.post("/webhook", data="not json", content_type="application/json")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


@pytest.mark.parametrize(
    "body, message_part",
    [
        ([1, 2, 3], "JSON-объект"),
        ({"type": "payment_succeeded"}, "event_id"),
        ({"event_id": "x"}, "type"),
        ({"event_id": "", "type": "payment_succeeded"}, "event_id"),
        ({"event_id": 123, "type": "payment_succeeded"}, "event_id"),
        ({"event_id": "x", "type": "payment_succeeded", "payload": "str"}, "payload"),
    ],
)
def test_invalid_event_returns_422_with_reason(client, conn, body, message_part):
    resp = client.post("/webhook", json=body)

    assert resp.status_code == 422
    assert message_part in resp.get_json()["error"]
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_stats_counts_events_by_type_and_tasks_by_status(client):
    client.post("/webhook", json=make_event("e1", "payment_succeeded"))
    client.post("/webhook", json=make_event("e2", "payment_succeeded"))
    client.post("/webhook", json=make_event("e3", "refund_created"))
    client.post("/webhook", json=make_event("e1", "payment_succeeded"))

    resp = client.get("/stats")

    assert resp.status_code == 200
    assert resp.get_json() == {
        "events": {"payment_succeeded": 2, "refund_created": 1},
        "tasks": {"pending": 3, "success": 0, "failed": 0, "skipped": 0},
    }
