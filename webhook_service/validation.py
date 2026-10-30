from dataclasses import dataclass
from typing import Any

MAX_ID_LENGTH = 255
MAX_TYPE_LENGTH = 100


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    event_id: str
    type: str
    payload: dict[str, Any]


def parse_event(body: Any) -> Event:
    if not isinstance(body, dict):
        raise ValidationError("Ожидается JSON-объект")

    event_id = _required_string(body, "event_id", MAX_ID_LENGTH)
    event_type = _required_string(body, "type", MAX_TYPE_LENGTH)

    payload = body.get("payload", {})
    if not isinstance(payload, dict):
        raise ValidationError("Поле 'payload' должно быть объектом")

    return Event(event_id=event_id, type=event_type, payload=payload)


def _required_string(body: dict, field: str, max_length: int) -> str:
    if field not in body:
        raise ValidationError(f"Не хватает поля '{field}'")
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Поле '{field}' должно быть непустой строкой")
    if len(value) > max_length:
        raise ValidationError(f"Поле '{field}' длиннее {max_length} символов")
    return value.strip()
