# Python 3.12, агрегат заказа без внешних зависимостей, прогнано на стенде 2026-11-06
"""Агрегат «заказ»: команды решают, какие события записать, свертка восстанавливает состояние.

Состояние нигде не хранится как источник истины. Его всегда можно получить заново,
свернув события потока по порядку версий.
"""
from decimal import Decimal


class DomainError(Exception):
    """Команда нарушает инвариант агрегата и отклоняется до записи в журнал."""


def initial_state(order_id: str) -> dict:
    return {"order_id": order_id, "status": None, "customer": None, "lines": {}, "version": 0}


def apply(state: dict, event_type: str, payload: dict, version: int) -> dict:
    """Одно событие меняет состояние. Здесь нет проверок: событие уже случилось."""
    s = {**state, "lines": dict(state["lines"]), "version": version}
    if event_type == "OrderCreated":
        s["status"] = "new"
        s["customer"] = payload["customer"]
    elif event_type == "ItemAdded":
        line = s["lines"].get(payload["sku"], {"qty": 0, "price": payload["price"]})
        s["lines"][payload["sku"]] = {"qty": line["qty"] + payload["qty"], "price": payload["price"]}
    elif event_type == "ItemRemoved":
        s["lines"].pop(payload["sku"], None)
    elif event_type == "OrderPaid":
        s["status"] = "paid"
    elif event_type == "OrderShipped":
        s["status"] = "shipped"
    else:
        raise ValueError(f"неизвестный тип события {event_type}")
    return s


def fold(events, state: dict) -> dict:
    """Свертка: левый fold списка событий поверх начального состояния или снапшота."""
    for e in events:
        state = apply(state, e.event_type, e.payload, e.stream_version)
    return state


def total(state: dict) -> Decimal:
    return sum((Decimal(l["price"]) * l["qty"] for l in state["lines"].values()), Decimal("0.00"))


# ---- команды: проверяют инварианты на текущем состоянии и возвращают новые события ----

def create(state: dict, customer: str) -> list[tuple[str, dict]]:
    if state["status"] is not None:
        raise DomainError(f"заказ {state['order_id']} уже создан")
    return [("OrderCreated", {"customer": customer})]


def add_item(state: dict, sku: str, qty: int, price: str) -> list[tuple[str, dict]]:
    if state["status"] != "new":
        raise DomainError(f"заказ в статусе {state['status']}, позиции менять нельзя")
    if qty <= 0:
        raise DomainError("количество должно быть больше нуля")
    return [("ItemAdded", {"sku": sku, "qty": qty, "price": price, "currency": "RUB"})]


def remove_item(state: dict, sku: str) -> list[tuple[str, dict]]:
    if state["status"] != "new":
        raise DomainError(f"заказ в статусе {state['status']}, позиции менять нельзя")
    if sku not in state["lines"]:
        raise DomainError(f"позиции {sku} в заказе нет")
    return [("ItemRemoved", {"sku": sku})]


def pay(state: dict, amount: str) -> list[tuple[str, dict]]:
    if state["status"] != "new":
        raise DomainError(f"заказ в статусе {state['status']}, оплатить нельзя")
    if not state["lines"]:
        raise DomainError("пустой заказ не оплачивается")
    if Decimal(amount) != total(state):
        raise DomainError(f"сумма оплаты {amount} не равна сумме заказа {total(state)}")
    return [("OrderPaid", {"amount": amount})]


def ship(state: dict, carrier: str) -> list[tuple[str, dict]]:
    if state["status"] != "paid":
        raise DomainError(f"заказ в статусе {state['status']}, отгрузить нельзя")
    return [("OrderShipped", {"carrier": carrier})]
