import json

from flask import Flask, g, jsonify, request

from . import db
from .validation import ValidationError, parse_event

MAX_BODY_BYTES = 1024 * 1024


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or "events.db"
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES

    db.init_db(app.config["DB_PATH"])

    def get_conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.post("/webhook")
    def webhook():
        body = request.get_json(silent=True)
        if body is None:
            return _error("Тело запроса должно быть валидным JSON (Content-Type: application/json)", 400)
        try:
            event = parse_event(body)
        except ValidationError as exc:
            return _error(str(exc), 422)

        created = db.save_event(
            get_conn(),
            event_id=event.event_id,
            event_type=event.type,
            payload=json.dumps(event.payload, ensure_ascii=False),
        )
        if created:
            return jsonify(event_id=event.event_id, status="accepted"), 202
        return jsonify(event_id=event.event_id, status="duplicate"), 200

    @app.get("/stats")
    def stats():
        return jsonify(db.get_stats(get_conn()))

    @app.errorhandler(413)
    def too_large(_exc):
        return _error(f"Тело запроса больше {MAX_BODY_BYTES} байт", 413)

    @app.errorhandler(405)
    def method_not_allowed(_exc):
        return _error("Метод не поддерживается", 405)

    return app


def _error(message: str, code: int):
    return jsonify(error=message), code
