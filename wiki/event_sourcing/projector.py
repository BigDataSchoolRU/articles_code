# psycopg 3.3.8, postgres 18.6 в Docker, прогнано на стенде 2026-11-06
"""Асинхронный проектор: читает журнал после чекпойнта и обновляет модель чтения order_summary.

Модель чтения и чекпойнт обновляются в одной транзакции: упал посередине, значит не сдвинулся
ни чекпойнт, ни модель. Повторно доставленное событие отсекается по версии потока.
"""
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

from event_store import Event, read_all_safe

NAME = "order_summary"


def _apply(cur, e: Event) -> bool:
    """Применить событие к модели чтения. False, если событие уже было учтено."""
    row = cur.execute("SELECT customer, status, lines, version FROM order_summary "
                      "WHERE order_id = %s FOR UPDATE", [e.stream_id]).fetchone()
    if row is not None and e.stream_version <= row[3]:
        return False  # повторная доставка: эта версия потока уже в модели
    if e.event_type == "OrderCreated":
        customer, status, lines = e.payload["customer"], "new", {}
    else:
        customer, status, lines = row[0], row[1], dict(row[2])
        if e.event_type == "ItemAdded":
            qty = lines.get(e.payload["sku"], {}).get("qty", 0) + e.payload["qty"]
            lines[e.payload["sku"]] = {"qty": qty, "price": e.payload["price"]}
        elif e.event_type == "ItemRemoved":
            lines.pop(e.payload["sku"], None)
        elif e.event_type == "OrderPaid":
            status = "paid"
        elif e.event_type == "OrderShipped":
            status = "shipped"
    items = sum(l["qty"] for l in lines.values())
    amount = sum((Decimal(l["price"]) * l["qty"] for l in lines.values()), Decimal("0.00"))
    cur.execute(
        "INSERT INTO order_summary (order_id, customer, status, lines, items_count, total, version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (order_id) DO UPDATE SET status = EXCLUDED.status, lines = EXCLUDED.lines, "
        "items_count = EXCLUDED.items_count, total = EXCLUDED.total, version = EXCLUDED.version",
        [e.stream_id, customer, status, Jsonb(lines), items, amount, e.stream_version])
    return True


def run_once(conn: psycopg.Connection, batch: int = 1000) -> tuple[int, int]:
    """Один проход: прочитать пачку после чекпойнта, применить, сдвинуть чекпойнт.

    Возвращает (прочитано, применено).
    """
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("INSERT INTO projection_checkpoints (projection) VALUES (%s) "
                    "ON CONFLICT DO NOTHING", [NAME])
        last_tx, last_pos = cur.execute(
            "SELECT last_tx::text, last_position FROM projection_checkpoints "
            "WHERE projection = %s FOR UPDATE", [NAME]).fetchone()
        events = read_all_safe(conn, int(last_tx), last_pos, batch)
        applied = sum(_apply(cur, e) for e in events)
        if events:
            cur.execute("UPDATE projection_checkpoints SET last_tx = %s::xid8, last_position = %s "
                        "WHERE projection = %s",
                        [str(events[-1].transaction_id), events[-1].global_position, NAME])
    return len(events), applied


def catch_up(conn: psycopg.Connection) -> tuple[int, int]:
    """Крутить проходы, пока журнал не кончится."""
    read_total = applied_total = 0
    while True:
        n, a = run_once(conn)
        read_total, applied_total = read_total + n, applied_total + a
        if n == 0:
            return read_total, applied_total


def reset(conn: psycopg.Connection, drop_model: bool) -> None:
    """Сбросить чекпойнт; с drop_model ещё и стереть модель чтения для пересборки с нуля."""
    with conn.transaction():
        if drop_model:
            conn.execute("TRUNCATE order_summary")
        conn.execute("DELETE FROM projection_checkpoints WHERE projection = %s", [NAME])
