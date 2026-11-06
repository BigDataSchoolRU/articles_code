# psycopg 3.3.8, postgres 18.6 в Docker, прогнано на стенде 2026-11-06
"""Демо Event Sourcing на PostgreSQL: запись и свертка, конфликт писателей, проекция,
снапшот, апкастер.

Запуск: python es_demo.py all | append | conflict | projection | snapshot | upcast
Адрес базы берётся из ES_DSN, по умолчанию postgresql://demo:demo@127.0.0.1:55437/es
"""
import os
import statistics
import sys
import time

import psycopg
from psycopg.types.json import Jsonb

import order
import projector
from event_store import (ConcurrencyError, append, insert_events, read_all_naive,
                         read_all_safe, read_stream)

DSN = os.environ.get("ES_DSN", "postgresql://demo:demo@127.0.0.1:55437/es")


def connect() -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=True)


def load(conn, order_id: str, to_version: int | None = None) -> dict:
    """Восстановить агрегат: прочитать поток и свернуть события по порядку версий."""
    return order.fold(read_stream(conn, order_id, to_version=to_version), order.initial_state(order_id))


def handle(conn, order_id: str, command, *args) -> int:
    """Обработчик команды: загрузить, проверить инварианты, дописать с ожидаемой версией."""
    state = load(conn, order_id)
    return append(conn, order_id, state["version"], command(state, *args),
                  metadata={"command": command.__name__})


def show_state(label: str, s: dict) -> None:
    lines = ", ".join(f"{k}×{v['qty']} по {v['price']}" for k, v in sorted(s["lines"].items()))
    print(f"  {label}: версия {s['version']}, статус {s['status']}, позиции [{lines}], "
          f"сумма {order.total(s)}")


# ---------------------------------------------------------------------------------------------

def demo_append(conn) -> None:
    print("\n=== 1. APPEND: запись событий и восстановление состояния ===")
    oid = "order-1001"
    handle(conn, oid, order.create, "alice")
    handle(conn, oid, order.add_item, "book", 2, "1290.00")
    handle(conn, oid, order.add_item, "lamp", 1, "3490.00")
    handle(conn, oid, order.remove_item, "lamp")
    handle(conn, oid, order.add_item, "pen", 3, "150.00")
    s = load(conn, oid)
    handle(conn, oid, order.pay, str(order.total(s)))
    handle(conn, oid, order.ship, "cdek")

    print("Журнал потока", oid)
    for r in conn.execute(
            "SELECT global_position, stream_version, event_type, schema_version, payload::text "
            "FROM events WHERE stream_id = %s ORDER BY stream_version", [oid]):
        print(f"  pos={r[0]:<3} v={r[1]} {r[2]:<13} schema=v{r[3]} {r[4]}")

    show_state("состояние сейчас (свертка 7 событий)", load(conn, oid))
    show_state("состояние на версии 3 (свертка первых 3)", load(conn, oid, to_version=3))
    show_state("состояние на версии 4 (после удаления lamp)", load(conn, oid, to_version=4))

    print("Команда против инварианта: добавить позицию в отгруженный заказ")
    try:
        handle(conn, oid, order.add_item, "mug", 1, "590.00")
    except order.DomainError as e:
        print("  отклонено до записи:", e)

    print("Попытка исправить историю прямо в таблице")
    for sql in ("UPDATE events SET payload = jsonb_set(payload, '{qty}', '5') "
                "WHERE stream_id = 'order-1001' AND stream_version = 2",
                "DELETE FROM events WHERE stream_id = 'order-1001' AND stream_version = 4",
                "TRUNCATE events"):
        try:
            conn.execute(sql)
        except psycopg.Error as e:
            print(f"  {sql.split()[0]}: {e.sqlstate} {e.diag.message_primary}")
    print("  событий в потоке после попыток:",
          conn.execute("SELECT count(*) FROM events WHERE stream_id = %s", [oid]).fetchone()[0])


def demo_conflict(conn) -> None:
    print("\n=== 2. CONFLICT: оптимистичная конкурентность ===")
    oid = "order-2002"
    handle(conn, oid, order.create, "bob")
    handle(conn, oid, order.add_item, "book", 1, "1290.00")
    w1, w2 = connect(), connect()

    print("Пара А: два писателя добавляют разные позиции")
    s1, s2 = load(w1, oid), load(w2, oid)
    print(f"  писатель 1 прочитал версию {s1['version']}, писатель 2 прочитал версию {s2['version']}")
    v = append(w1, oid, s1["version"], order.add_item(s1, "lamp", 1, "3490.00"))
    print(f"  писатель 1 записал ItemAdded(lamp) с ожидаемой версией {s1['version']} -> версия {v}")
    try:
        append(w2, oid, s2["version"], order.add_item(s2, "pen", 2, "150.00"))
    except ConcurrencyError as e:
        print(f"  писатель 2: {e.__cause__.sqlstate} {type(e.__cause__).__name__}: {e}")
        s2 = load(w2, oid)
        print(f"  писатель 2 перечитал поток: версия {s2['version']}, позиции {sorted(s2['lines'])}")
        v = append(w2, oid, s2["version"], order.add_item(s2, "pen", 2, "150.00"))
        print(f"  писатель 2 повторил команду -> версия {v}")

    print("Пара Б: писатель 1 оплачивает, писатель 2 в это время добавляет позицию")
    s1, s2 = load(w1, oid), load(w2, oid)
    print(f"  оба прочитали версию {s1['version']}")
    v = append(w1, oid, s1["version"], order.pay(s1, str(order.total(s1))))
    print(f"  писатель 1 записал OrderPaid -> версия {v}")
    try:
        append(w2, oid, s2["version"], order.add_item(s2, "mug", 1, "590.00"))
    except ConcurrencyError as e:
        print(f"  писатель 2: {e.__cause__.sqlstate} {type(e.__cause__).__name__}: {e}")
        s2 = load(w2, oid)
        print(f"  писатель 2 перечитал поток: версия {s2['version']}, статус {s2['status']}")
        try:
            append(w2, oid, s2["version"], order.add_item(s2, "mug", 1, "590.00"))
        except order.DomainError as de:
            print("  повтор команды отклонён инвариантом:", de)
    show_state("итог", load(conn, oid))
    for c in (w1, w2):
        c.close()


def demo_projection(conn) -> None:
    print("\n=== 3. PROJECTION: модель чтения, повторная доставка, пересборка ===")
    oid = "order-3003"
    handle(conn, oid, order.create, "carol")
    handle(conn, oid, order.add_item, "lamp", 2, "3490.00")

    projector.reset(conn, drop_model=True)
    n, a = projector.catch_up(conn)
    print(f"Первый проход: прочитано {n}, применено {a}")
    cp = conn.execute("SELECT last_tx::text, last_position FROM projection_checkpoints").fetchone()
    print(f"  чекпойнт: last_tx={cp[0]}, last_position={cp[1]}")
    n, a = projector.catch_up(conn)
    print(f"Второй проход без новых событий: прочитано {n}, применено {a}")

    summary_sql = ("SELECT order_id, customer, status, items_count, total, version "
                   "FROM order_summary ORDER BY order_id")
    before = conn.execute(summary_sql).fetchall()
    print("Модель чтения order_summary:")
    for r in before:
        print(f"  {r[0]} {r[1]:<6} {r[2]:<8} позиций={r[3]} сумма={r[4]} версия={r[5]}")

    projector.reset(conn, drop_model=False)
    n, a = projector.catch_up(conn)
    print(f"Чекпойнт сброшен, модель оставлена (повторная доставка всего журнала): "
          f"прочитано {n}, применено {a}")

    projector.reset(conn, drop_model=True)
    n, a = projector.catch_up(conn)
    after = conn.execute(summary_sql).fetchall()
    print(f"Пересборка с нуля (TRUNCATE модели и чекпойнта): прочитано {n}, применено {a}, "
          f"модель совпала с прежней: {before == after}")

    print("Ловушка глобальной позиции: транзакция A взяла позицию раньше B, а зафиксировалась позже")
    a_conn, b_conn, reader = connect(), connect(), connect()
    last = conn.execute("SELECT max(global_position) FROM events").fetchone()[0]
    last_tx = int(conn.execute("SELECT max(transaction_id)::text FROM events").fetchone()[0])
    naive_seen, safe_seen = [], []
    naive_pos, safe_cp = last, (last_tx, last)

    def poll(step: str) -> None:
        nonlocal naive_pos, safe_cp
        got_n = read_all_naive(reader, naive_pos)
        got_s = read_all_safe(reader, *safe_cp)
        if got_n:
            naive_pos = got_n[-1].global_position
        if got_s:
            safe_cp = (got_s[-1].transaction_id, got_s[-1].global_position)
        naive_seen.extend(e.global_position for e in got_n)
        safe_seen.extend(e.global_position for e in got_s)
        print(f"  {step}: наивный прочитал {[e.global_position for e in got_n]}, чекпойнт {naive_pos}; "
              f"по горизонту прочитал {[e.global_position for e in got_s]}")

    with a_conn.transaction(), a_conn.cursor() as cur:
        insert_events(cur, "order-4004", 0, order.create(order.initial_state("order-4004"), "dave"))
        pos_a = cur.execute("SELECT max(global_position) FROM events").fetchone()[0]
        print(f"  A: вставил OrderCreated(order-4004), позиция {pos_a}, транзакция открыта")
        append(b_conn, "order-5005", 0, order.create(order.initial_state("order-5005"), "erin"))
        pos_b = b_conn.execute("SELECT max(global_position) FROM events").fetchone()[0]
        print(f"  B: вставил OrderCreated(order-5005), позиция {pos_b}, COMMIT")
        poll("опрос 1, A ещё открыта")
    print("  A: COMMIT")
    poll("опрос 2, обе зафиксированы")
    poll("опрос 3")
    print(f"  итог: наивный проектор увидел {naive_seen}, пропущена позиция {pos_a}: "
          f"{pos_a not in naive_seen}; по горизонту увидел {safe_seen}")
    for c in (a_conn, b_conn, reader):
        c.close()


def demo_snapshot(conn) -> None:
    print("\n=== 4. SNAPSHOT: полная свертка против снапшота плюс хвост ===")
    oid = "order-6006"
    n_bulk, n_tail = 10_000, 20
    # длинный поток: позиции по кругу добавляются и удаляются, состояние остаётся маленьким
    bulk = [("OrderCreated", {"customer": "frank"})]
    for i in range(1, n_bulk):
        sku = f"sku-{i % 50:02d}"
        if i % 7 == 0:
            bulk.append(("ItemRemoved", {"sku": sku}))
        else:
            bulk.append(("ItemAdded", {"sku": sku, "qty": 1, "price": "100.00", "currency": "RUB"}))
    t = time.perf_counter()
    append(conn, oid, 0, bulk)
    print(f"Записано {n_bulk} событий одной транзакцией за {(time.perf_counter() - t) * 1000:.0f} мс")

    s = load(conn, oid)
    conn.execute("INSERT INTO snapshots (stream_id, stream_version, state) VALUES (%s, %s, %s) "
                 "ON CONFLICT (stream_id) DO UPDATE SET stream_version = EXCLUDED.stream_version, "
                 "state = EXCLUDED.state", [oid, s["version"], Jsonb(s)])
    print(f"Снапшот сохранён на версии {s['version']}")
    tail = [("ItemAdded", {"sku": f"tail-{i:02d}", "qty": 1, "price": "10.00", "currency": "RUB"})
            for i in range(n_tail)]
    append(conn, oid, s["version"], tail)

    def full():
        return load(conn, oid)

    def with_snapshot():
        version, state = conn.execute(
            "SELECT stream_version, state FROM snapshots WHERE stream_id = %s", [oid]).fetchone()
        return order.fold(read_stream(conn, oid, after_version=version), state)

    def measure(fn, runs=7):
        times, result = [], None
        for _ in range(runs):
            t = time.perf_counter()
            result = fn()
            times.append((time.perf_counter() - t) * 1000)
        return statistics.median(times), result

    full()  # прогрев кэша страниц и соединения
    t_full, s_full = measure(full)
    t_snap, s_snap = measure(with_snapshot)
    print(f"Полная свертка {s_full['version']} событий: медиана {t_full:.1f} мс из 7 запусков")
    print(f"Снапшот на версии {s['version']} плюс хвост {n_tail} событий: медиана {t_snap:.1f} мс")
    print(f"Ускорение: {t_full / t_snap:.0f}×, состояния совпали: {s_full == s_snap}")
    print(f"  состояние: версия {s_snap['version']}, статус {s_snap['status']}, "
          f"разных позиций {len(s_snap['lines'])}, сумма {order.total(s_snap)}")


def demo_upcast(conn) -> None:
    print("\n=== 5. UPCAST: старая версия события поднимается при чтении ===")
    oid = "order-7007"
    # старый код писал ItemAdded v1: цена целым числом в рублях, без валюты
    conn.execute(
        "INSERT INTO events (stream_id, stream_version, event_type, schema_version, payload) VALUES "
        "(%s, 1, 'OrderCreated', 1, '{\"customer\": \"grace\"}'), "
        "(%s, 2, 'ItemAdded', 1, '{\"sku\": \"book\", \"qty\": 2, \"price\": 1290}')", [oid, oid])
    # новый код пишет только v2
    handle(conn, oid, order.add_item, "pen", 3, "150.50")

    count_sql = ("SELECT schema_version, count(*) FROM events "
                 "WHERE event_type = 'ItemAdded' AND stream_id = %s GROUP BY 1 ORDER BY 1")
    before = conn.execute(count_sql, [oid]).fetchall()
    print("В журнале как записано:")
    for r in conn.execute("SELECT stream_version, event_type, schema_version, payload::text FROM events "
                          "WHERE stream_id = %s ORDER BY stream_version", [oid]):
        print(f"  v={r[0]} {r[1]:<13} schema=v{r[2]} {r[3]}")
    print("После чтения через апкастер:")
    for e in read_stream(conn, oid):
        print(f"  v={e.stream_version} {e.event_type:<13} schema=v{e.schema_version} {e.payload}")
    show_state("состояние", load(conn, oid))
    after = conn.execute(count_sql, [oid]).fetchall()
    print(f"ItemAdded по версиям схемы в журнале до чтения {before}, после {after}, "
          f"журнал не изменился: {before == after}")


DEMOS = {"append": demo_append, "conflict": demo_conflict, "projection": demo_projection,
         "snapshot": demo_snapshot, "upcast": demo_upcast}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode != "all" and mode not in DEMOS:
        print(__doc__)
        return 2
    with connect() as conn:
        print("PostgreSQL:", conn.execute("SHOW server_version").fetchone()[0],
              "| psycopg", psycopg.__version__)
        for name, fn in DEMOS.items():
            if mode in ("all", name):
                fn(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
