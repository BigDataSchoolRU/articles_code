# psycopg 3.3.8, postgres 18.6 в Docker, прогнано на стенде 2026-11-06
"""Хранилище событий на одной таблице PostgreSQL: запись с ожидаемой версией, чтение потока,
чтение журнала для проектора и апкастеры старых версий событий."""
from dataclasses import dataclass
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

# Текущая версия схемы для каждого типа события. Новые события пишутся только в ней.
CURRENT_SCHEMA = {"ItemAdded": 2}


class ConcurrencyError(Exception):
    """Кто-то успел записать в поток раньше: ожидаемая версия устарела."""

    def __init__(self, stream_id: str, expected_version: int):
        super().__init__(f"поток {stream_id}: ожидали версию {expected_version}, она уже занята")
        self.stream_id = stream_id
        self.expected_version = expected_version


@dataclass(frozen=True)
class Event:
    global_position: int
    stream_id: str
    stream_version: int
    event_type: str
    schema_version: int
    payload: dict
    transaction_id: int = 0


# ---- апкастеры: поднимают старую версию payload до текущей при чтении, журнал не трогают ----

def _item_added_v1_to_v2(p: dict) -> dict:
    # v1: {"sku", "qty", "price": 1290} цена целым числом в рублях
    # v2: {"sku", "qty", "price": "1290.00", "currency": "RUB"}
    return {"sku": p["sku"], "qty": p["qty"],
            "price": str(Decimal(p["price"]).quantize(Decimal("0.01"))), "currency": "RUB"}


UPCASTERS = {("ItemAdded", 1): (2, _item_added_v1_to_v2)}


def upcast(event_type: str, schema_version: int, payload: dict) -> tuple[int, dict]:
    # цепочка: v1 -> v2 -> ... пока для пары (тип, версия) есть апкастер
    while (event_type, schema_version) in UPCASTERS:
        schema_version, fn = UPCASTERS[(event_type, schema_version)]
        payload = fn(payload)
    return schema_version, payload


def _row_to_event(row) -> Event:
    pos, stream_id, version, etype, schema, payload, tx = row
    schema, payload = upcast(etype, schema, payload)
    return Event(pos, stream_id, version, etype, schema, payload, int(tx))


_COLUMNS = ("global_position, stream_id, stream_version, event_type, schema_version, payload, "
            "transaction_id::text")


# ---- запись ----

def insert_events(cur, stream_id: str, expected_version: int, events, metadata=None) -> int:
    """INSERT без управления транзакцией: версии идут подряд после ожидаемой."""
    rows = [(stream_id, expected_version + i, etype, CURRENT_SCHEMA.get(etype, 1),
             Jsonb(payload), Jsonb(metadata or {}))
            for i, (etype, payload) in enumerate(events, start=1)]
    cur.executemany(
        "INSERT INTO events (stream_id, stream_version, event_type, schema_version, payload, metadata) "
        "VALUES (%s, %s, %s, %s, %s, %s)", rows)
    return expected_version + len(rows)


def append(conn: psycopg.Connection, stream_id: str, expected_version: int, events,
           metadata=None) -> int:
    """Дописать события в поток одной транзакцией. Возвращает новую версию потока.

    Проверку версии делает уникальный индекс (stream_id, stream_version): если другой
    писатель уже занял версию expected_version + 1, вставка падает с 23505.
    """
    try:
        with conn.transaction(), conn.cursor() as cur:
            return insert_events(cur, stream_id, expected_version, events, metadata)
    except psycopg.errors.UniqueViolation as e:
        raise ConcurrencyError(stream_id, expected_version) from e


# ---- чтение потока ----

def read_stream(conn: psycopg.Connection, stream_id: str, after_version: int = 0,
                to_version: int | None = None) -> list[Event]:
    sql = f"SELECT {_COLUMNS} FROM events WHERE stream_id = %s AND stream_version > %s"
    params: list = [stream_id, after_version]
    if to_version is not None:
        sql += " AND stream_version <= %s"
        params.append(to_version)
    rows = conn.execute(sql + " ORDER BY stream_version", params).fetchall()
    return [_row_to_event(r) for r in rows]


# ---- чтение журнала проектором ----

def read_all_naive(conn: psycopg.Connection, after_position: int, limit: int = 1000) -> list[Event]:
    """Наивно: всё, что больше последней прочитанной позиции.

    Пропускает событие, если его транзакция взяла позицию раньше соседней, а зафиксировалась позже.
    """
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM events WHERE global_position > %s ORDER BY global_position LIMIT %s",
        [after_position, limit]).fetchall()
    return [_row_to_event(r) for r in rows]


def read_all_safe(conn: psycopg.Connection, after_tx: int, after_position: int,
                  limit: int = 1000) -> list[Event]:
    """Только события транзакций ниже горизонта: xid меньше xmin текущего снимка.

    Все такие транзакции уже завершены, новых с меньшим xid не появится, поэтому порядок
    (transaction_id, global_position) растёт без дыр. Цена: пока открыта долгая пишущая
    транзакция, проектор стоит и ждёт её.
    """
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM events "
        "WHERE (transaction_id, global_position) > (%s::xid8, %s) "
        "  AND transaction_id < pg_snapshot_xmin(pg_current_snapshot()) "
        "ORDER BY transaction_id, global_position LIMIT %s",
        [str(after_tx), after_position, limit]).fetchall()
    return [_row_to_event(r) for r in rows]
