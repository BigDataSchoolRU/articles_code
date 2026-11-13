# psycopg 3.3.8, PostgreSQL 18.6, прогнано на стенде 2026-11-13
"""Активные метаданные на событиях PostgreSQL: событие -> фильтр -> правило -> действие.

Слушатель получает id события через LISTEN, читает событие из meta.events и применяет правила:
  pii_by_name     новая колонка с именем email, phone, passport, birth_date получает тег pii;
  pii_propagation представление, которое читает колонку с тегом pii, получает тег и теряет
                  SELECT у роли analyst (тег идёт по lineage дальше, представление над представлением);
  impact_on_drop  удаление колонки или представления: по lineage находим внешних потребителей и шлём алерт.
События, которые породил сам слушатель (его REVOKE тоже DDL), отсекаются фильтром, иначе возникает петля.
"""
import os
import re
import time

import psycopg

DSN = os.environ.get("META_DSN", "host=127.0.0.1 port=55441 user=demo password=demo dbname=demo")
CHANNEL = "meta_events"
SELF_APP = "active_metadata"
PII_RE = re.compile(r"(email|phone|passport|birth_date)")

stats = {"events": 0, "self": 0, "actions": 0}


def connect(app: str) -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=True, application_name=app)


def reset(conn: psycopg.Connection) -> None:
    """Исходное состояние: таблица без представлений, пустой граф, только внешние потребители."""
    conn.execute("DROP TABLE IF EXISTS raw.customers CASCADE")
    conn.execute("CREATE TABLE raw.customers (id int PRIMARY KEY, name text NOT NULL, city text)")
    conn.execute(
        "INSERT INTO raw.customers VALUES (1, 'Анна', 'Москва'), (2, 'Борис', 'Казань'), (3, 'Вера', 'Москва')"
    )
    conn.execute("TRUNCATE meta.events, meta.columns, meta.tags, meta.actions RESTART IDENTITY")
    conn.execute("DELETE FROM meta.lineage WHERE kind <> 'consumer'")


def bootstrap(cat: psycopg.Connection) -> None:
    """Первичный обход: события несут только изменения, базовое состояние каталог снимает сам."""
    cat.execute(
        "INSERT INTO meta.columns SELECT table_schema || '.' || table_name, column_name "
        "FROM information_schema.columns WHERE table_schema IN ('raw', 'mart', 'report')"
    )


# ── действия ──────────────────────────────────────────────────────────────

def act(cat: psycopg.Connection, eid: int, rule: str, asset: str, action: str) -> None:
    cat.execute("INSERT INTO meta.actions (event, rule, asset, action) VALUES (%s, %s, %s, %s)",
                (eid, rule, asset, action))
    stats["actions"] += 1
    print(f"      -> [{rule}] {asset}: {action}")


def tag(cat: psycopg.Connection, eid: int, rule: str, asset: str, source: str) -> None:
    cur = cat.execute(
        "INSERT INTO meta.tags (asset, tag, source) VALUES (%s, 'pii', %s) ON CONFLICT DO NOTHING", (asset, source)
    )
    if cur.rowcount:
        act(cat, eid, rule, asset, f"тег pii ({source})")


def is_pii(cat: psycopg.Connection, column: str) -> bool:
    """Колонка считается pii, если тег стоит на ней самой или на всём представлении, которому она принадлежит."""
    relation = column.rsplit(".", 1)[0]
    return cat.execute(
        "SELECT EXISTS (SELECT 1 FROM meta.tags WHERE tag = 'pii' AND asset IN (%s, %s))", (column, relation)
    ).fetchone()[0]


# ── правила ───────────────────────────────────────────────────────────────

def on_table_changed(cat: psycopg.Connection, eid: int, obj: dict) -> None:
    """Событие говорит «ALTER TABLE raw.customers», какая колонка, видно только сравнением составов."""
    rel = obj["identity"]
    before = {r[0] for r in cat.execute("SELECT column_name FROM meta.columns WHERE relation = %s", (rel,))}
    after = set(obj["columns"] or [])
    added, removed = sorted(after - before), sorted(before - after)
    print(f"      сравнение с каталогом: добавлены {added}, удалены {removed}")
    cat.execute("DELETE FROM meta.columns WHERE relation = %s", (rel,))
    cat.cursor().executemany("INSERT INTO meta.columns VALUES (%s, %s)", [(rel, c) for c in sorted(after)])
    for col in added:
        if PII_RE.search(col):
            tag(cat, eid, "pii_by_name", f"{rel}.{col}", f"имя колонки совпало с {PII_RE.pattern}")


def on_view_created(cat: psycopg.Connection, eid: int, obj: dict) -> None:
    view, reads = obj["identity"], obj["reads"] or []
    print(f"      lineage: {view} читает {reads}")
    cat.cursor().executemany("INSERT INTO meta.lineage VALUES (%s, %s, 'view') ON CONFLICT DO NOTHING",
                    [(col, view) for col in reads])
    cat.cursor().executemany("INSERT INTO meta.columns VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    [(view, c) for c in obj["columns"] or []])
    pii_sources = [col for col in reads if is_pii(cat, col)]
    if pii_sources:
        tag(cat, eid, "pii_propagation", view, f"читает {', '.join(pii_sources)}")
        cat.execute(f"REVOKE SELECT ON {view} FROM analyst")
        act(cat, eid, "pii_propagation", view, "REVOKE SELECT FROM analyst")


def on_dropped(cat: psycopg.Connection, eid: int, objects: list[dict]) -> None:
    dropped = [o["identity"] for o in objects]
    for o in objects:
        how = "назван в команде" if o["original"] else "снесён каскадом"
        print(f"      удалён {o['type']} {o['identity']} ({how})")
    # Обход lineage вниз от удалённых объектов. Граф хранится в каталоге: из pg_depend зависимости
    # удалённого представления уже исчезли вместе с ним
    rows = cat.execute(
        """
        WITH RECURSIVE down(asset, path) AS (
            SELECT d, d FROM unnest(%s::text[]) AS d
            UNION
            SELECT l.downstream, down.path || ' -> ' || l.downstream
            FROM meta.lineage l
            JOIN down ON l.upstream = down.asset OR starts_with(l.upstream, down.asset || '.')
        )
        -- до потребителя можно дойти несколькими путями, берём самый длинный
        SELECT DISTINCT ON (d.asset) d.asset, d.path FROM down d
        JOIN meta.lineage l ON l.downstream = d.asset AND l.kind = 'consumer'
        ORDER BY d.asset, length(d.path) DESC
        """,
        (dropped,),
    ).fetchall()
    for consumer, path in rows:
        act(cat, eid, "impact_on_drop", consumer, f"АЛЕРТ владельцу: сломан источник, путь {path}")
    if not rows:
        print("      внешних потребителей ниже по lineage нет")
    # граф чистится от удалённого
    for asset in dropped:
        cat.execute("DELETE FROM meta.lineage WHERE upstream = %s OR starts_with(upstream, %s) OR downstream = %s",
                    (asset, asset + ".", asset))
        cat.execute("DELETE FROM meta.columns WHERE relation = %s", (asset,))


def handle(cat: psycopg.Connection, eid: int) -> None:
    event, tag_, app, objects, lag_ms = cat.execute(
        "SELECT event, tag, app, objects, round(extract(epoch FROM clock_timestamp() - at) * 1000) "
        "FROM meta.events WHERE id = %s", (eid,)
    ).fetchone()
    stats["events"] += 1
    idents = ", ".join(f"{o['type']} {o['identity']}" for o in objects)
    print(f"  событие #{eid} {event} {tag_} от {app}: {idents} (через {lag_ms:.0f} мс после записи)")
    # фильтр: своё событие (REVOKE слушателя) не обрабатываем, иначе правило может запустить само себя
    if app == SELF_APP:
        stats["self"] += 1
        print("      пропущено фильтром: событие порождено действием самого слушателя")
        return
    if event == "sql_drop":
        on_dropped(cat, eid, objects)
        return
    for obj in objects:
        if obj["type"] == "table":
            on_table_changed(cat, eid, obj)
        elif obj["type"] == "view":
            on_view_created(cat, eid, obj)


def run_step(sql: str, ddl: psycopg.Connection, listener: psycopg.Connection, cat: psycopg.Connection) -> None:
    print(f"\n>>> {sql}")
    ddl.execute(sql)
    # обработка идёт по мере прихода уведомлений; секунда тишины значит, что шаг отработан
    for n in listener.notifies(timeout=1.0):
        handle(cat, int(n.payload))


def check_access(conn: psycopg.Connection, relations: list[str]) -> None:
    for rel in relations:
        try:
            with conn.transaction():
                conn.execute("SET LOCAL ROLE analyst")
                cnt = conn.execute(f"SELECT count(*) FROM {rel}").fetchone()[0]
            print(f"  analyst SELECT {rel}: ok, строк {cnt}")
        except psycopg.errors.InsufficientPrivilege as e:
            print(f"  analyst SELECT {rel}: {e.diag.message_primary}")


def main() -> None:
    admin = connect("demo_reset")
    reset(admin)
    cat = connect(SELF_APP)          # каталог: читает события, пишет граф, выполняет действия
    bootstrap(cat)
    listener = connect(SELF_APP)
    listener.execute(f"LISTEN {CHANNEL}")
    ddl = connect("etl_migration")   # чужие изменения: миграции, аналитики, dbt

    print("=== Правила работают, пока идут миграции ===")
    t0 = time.monotonic()
    run_step("ALTER TABLE raw.customers ADD COLUMN email text", ddl, listener, cat)
    ddl.execute("UPDATE raw.customers SET email = lower(name) || '@example.com'")
    run_step("CREATE VIEW mart.customers_by_city AS SELECT city, count(*) AS customers FROM raw.customers GROUP BY city",
             ddl, listener, cat)
    run_step("CREATE VIEW mart.customer_contacts AS SELECT id, name, email FROM raw.customers", ddl, listener, cat)
    run_step("CREATE VIEW report.newsletter AS SELECT name, email FROM mart.customer_contacts WHERE email IS NOT NULL",
             ddl, listener, cat)

    print("\n=== Доступ аналитика после действий ===")
    check_access(ddl, ["mart.customers_by_city", "mart.customer_contacts", "report.newsletter"])

    print("\n=== Окно до действия: между записью события и REVOKE ===")
    for asset, ms in cat.execute(
        "SELECT a.asset, round(extract(epoch FROM a.at - e.at) * 1000) FROM meta.actions a "
        "JOIN meta.events e ON e.id = a.event WHERE a.action LIKE 'REVOKE%' ORDER BY a.id"
    ):
        print(f"  {asset}: {ms:.0f} мс, в это время analyst мог читать pii")

    run_step("ALTER TABLE raw.customers DROP COLUMN city CASCADE", ddl, listener, cat)

    print(f"\n=== Итог за {time.monotonic() - t0:.1f} с ===")
    print(f"событий {stats['events']}, из них своих отсечено {stats['self']}, действий {stats['actions']}")
    print("теги:")
    for asset, source in cat.execute("SELECT asset, source FROM meta.tags ORDER BY at"):
        print(f"  pii  {asset:<28} {source}")
    print("lineage в каталоге:")
    for up, down, kind in cat.execute("SELECT upstream, downstream, kind FROM meta.lineage ORDER BY kind, 1, 2"):
        print(f"  {up} -> {down} ({kind})")

    for c in (admin, cat, listener, ddl):
        c.close()


if __name__ == "__main__":
    main()
