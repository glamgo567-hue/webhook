import logging
import random
from typing import Any, Callable

log = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], None]


class SkipEvent(Exception):
    pass


class SimulatedFailure(Exception):
    pass


def _payment_succeeded(payload: dict) -> None:
    log.info("Отмечаем заказ %s оплаченным", payload.get("order_id"))


def _payment_failed(payload: dict) -> None:
    log.info("Уведомляем клиента о неудачной оплате заказа %s", payload.get("order_id"))


def _refund_created(payload: dict) -> None:
    log.info("Регистрируем возврат %s", payload.get("refund_id"))


HANDLERS: dict[str, Callable[[dict], None]] = {
    "payment_succeeded": _payment_succeeded,
    "payment_failed": _payment_failed,
    "refund_created": _refund_created,
}


def make_handler(fail_rate: float = 0.3,
                 rng: Callable[[], float] = random.random) -> Handler:

    def handle(event_type: str, payload: dict[str, Any]) -> None:
        action = HANDLERS.get(event_type)
        if action is None:
            raise SkipEvent(f"Нет обработчика для типа '{event_type}'")
        if rng() < fail_rate:
            raise SimulatedFailure(f"Имитация сбоя при обработке '{event_type}'")
        action(payload)

    return handle
