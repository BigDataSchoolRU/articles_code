# psycopg 3.3.8, PostgreSQL 18.6, прогнано на стенде 2026-11-13
"""Пассивный каталог против событий: что видит обход по расписанию и что видит слушатель.

1. Каталог снимает состав колонок дважды, между снимками колонку добавили и удалили.
2. Слушатель LISTEN получает каждое изменение отдельным событием.
3. Откаченная транзакция события не порождает.
4. Слушатель, который был отключён, уведомлений не получает, догоняет по журналу meta.events.
"""
import os
import time

import psycopg

DSN = os.environ.get("META_DSN", "host=127.0.0.1 port=55441 user=demo password=demo dbname=demo")
CHANNEL = "meta_events"


def connect(app: str) -> psycopg.Connection:
    # application_name попадает в событие: по нему видно, кто сделал изменение
    return psycopg.connect(DSN, autocommit=True, application_name=app)


def reset(conn: psycopg.Connection) -> None:
    """Исходное состояние: таблица из трёх колонок без представлений, пустой журнал. Слушателей пока нет."""
    conn.execute("DROP TABLE IF EXISTS raw.customers CASCADE")
    conn.execute("CREATE TABLE raw.customers (id int PRIMARY KEY, name text NOT NULL, city text)")
    conn.execute(
        "INSERT INTO raw.customers VALUES (1, 'Анна', 'Москва'), (2, 'Борис', 'Казань'), (3, 'Вера', 'Москва')"
    )
    conn.execute("TRUNCATE meta.events, meta.columns, meta.tags, meta.actions RESTART IDENTITY")
    conn.execute("DELETE FROM meta.lineage WHERE kind <> 'consumer'")


def crawl(conn: psycopg.Connection) -> set[str]:
    """Пассивный сбор: каталог сам ходит в information_schema и снимает текущее состояние."""
    rows = conn.execute(
        "SELECT table_schema || '.' || table_name || '.' || column_name "
        "FROM information_schema.columns WHERE table_schema = 'raw'"
    ).fetchall()
    return {r[0] for r in rows}


def drain(listener: psycopg.Connection, reader: psycopg.Connection, timeout: float = 1.0) -> list[tuple]:
    """Забрать уведомления, пришедшие за timeout секунд, и прочитать события из журнала по id."""
    ids = [int(n.payload) for n in listener.notifies(timeout=timeout)]
    if not ids:
        return []
    return reader.execute(
        "SELECT id, event, tag, app, objects FROM meta.events WHERE id = ANY(%s) ORDER BY id", (ids,)
    ).fetchall()


def show(events: list[tuple]) -> None:
    for eid, event, tag, app, objects in events:
        parts = []
        for o in objects:
            text = f"{o['type']} {o['identity']}"
            if o.get("columns"):
                text += f" колонки={o['columns']}"
            parts.append(text)
        print(f"  #{eid} {event:<15} {tag:<12} app={app:<14} {'; '.join(parts)}")


def main() -> None:
    admin = connect("demo_reset")
    reset(admin)

    print("=== 1. Пассивный каталог: два обхода по расписанию ===")
    crawler = connect("catalog_crawler")
    snap1 = crawl(crawler)
    print("обход 1:", sorted(snap1))

    listener = connect("catalog_listener")
    listener.execute(f"LISTEN {CHANNEL}")

    # Между обходами миграция добавляет временную колонку, удаляет её и добавляет постоянную
    migration = connect("etl_migration")
    for sql in (
        "ALTER TABLE raw.customers ADD COLUMN promo_code text",
        "UPDATE raw.customers SET promo_code = 'WELCOME10' WHERE id = 1",
        "ALTER TABLE raw.customers DROP COLUMN promo_code",
        "ALTER TABLE raw.customers ADD COLUMN phone text",
    ):
        migration.execute(sql)
        print("  миграция:", sql)

    snap2 = crawl(crawler)
    print("обход 2:", sorted(snap2))
    print("пассивный каталог видит: добавлено", sorted(snap2 - snap1), "удалено", sorted(snap1 - snap2))

    print()
    print("=== 2. Активный слой: те же изменения как события ===")
    reader = connect("catalog_reader")
    events = drain(listener, reader)
    show(events)
    print(f"событий получено: {len(events)}; UPDATE события не дал: это DML, а не DDL")

    print()
    print("=== 3. Откат: DDL внутри транзакции, которая не закоммитилась ===")
    try:
        with migration.transaction():
            migration.execute("ALTER TABLE raw.customers ADD COLUMN tmp_flag boolean")
            raise psycopg.Rollback()
    except psycopg.Rollback:
        pass
    events = drain(listener, reader)
    rows = reader.execute("SELECT count(*) FROM meta.events WHERE query LIKE '%tmp_flag%'").fetchone()[0]
    print(f"уведомлений после ROLLBACK: {len(events)}; строк в журнале про tmp_flag: {rows}")

    print()
    print("=== 4. Слушатель был отключён ===")
    last_seen = reader.execute("SELECT max(id) FROM meta.events").fetchone()[0]
    listener.close()
    migration.execute("ALTER TABLE raw.customers ADD COLUMN birth_date date")
    print("  миграция при отключённом слушателе: ALTER TABLE raw.customers ADD COLUMN birth_date date")

    listener = connect("catalog_listener")
    listener.execute(f"LISTEN {CHANNEL}")
    t0 = time.monotonic()
    events = drain(listener, reader, timeout=2.0)
    print(f"уведомлений после переподключения за {time.monotonic() - t0:.1f} с: {len(events)}")

    missed = reader.execute(
        "SELECT id, event, tag, app, objects FROM meta.events WHERE id > %s ORDER BY id", (last_seen,)
    ).fetchall()
    print(f"догоняем по журналу meta.events с id > {last_seen}: {len(missed)}")
    show(missed)

    for c in (admin, crawler, listener, migration, reader):
        c.close()


if __name__ == "__main__":
    main()
