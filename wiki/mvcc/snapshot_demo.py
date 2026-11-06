# psycopg 3.3.8, postgres 18.6 в Docker, прогнано на стенде 2026-11-06
"""Снимок данных и горизонт удаления в PostgreSQL на двух сессиях с явным чередованием шагов.

Шаги выполняются строго по очереди, поэтому результат не зависит от таймингов.

    python snapshot_demo.py snapshot   # чтение не ждёт запись, RR держит снимок, RC берёт новый
    python snapshot_demo.py horizon    # открытая транзакция не даёт VACUUM удалить мёртвые версии
    python snapshot_demo.py all        # оба сценария

Адрес сервера берётся из MVCC_DSN, по умолчанию локальный контейнер из docker-compose.yml.
"""
import os
import sys
import time

import psycopg

sys.stdout.reconfigure(line_buffering=True)

DSN = os.environ.get(
    "MVCC_DSN", "host=127.0.0.1 port=55436 dbname=mvcc user=demo password=demo"
)


def fmt(value):
    """Decimal, xid8 и снимки печатаем строкой, как в psql."""
    return value if isinstance(value, (int, bool)) or value is None else str(value)


class Session:
    """Одна сессия PostgreSQL. autocommit=True, чтобы BEGIN и COMMIT были видны явно."""

    def __init__(self, name):
        self.name = name
        self.conn = psycopg.connect(DSN, autocommit=True)
        self.notices = []
        # VACUUM (VERBOSE) отдаёт отчёт сообщениями уровня INFO, а не строками результата
        self.conn.add_notice_handler(lambda d: self.notices.append(d.message_primary))

    def run(self, sql, timed=False):
        print(f"[{self.name}] {sql}")
        t = time.perf_counter()
        cur = self.conn.execute(sql)
        ms = (time.perf_counter() - t) * 1000
        rows = [tuple(fmt(v) for v in row) for row in cur.fetchall()] if cur.description else None
        if rows is not None:
            print(f"      -> {rows}")
        if timed:
            print(f"      (выполнено за {ms:.1f} мс)")
        return rows

    def close(self):
        self.conn.close()


def snapshot(admin, a, b):
    admin.run("DROP TABLE IF EXISTS accounts CASCADE")
    admin.run(
        "CREATE TABLE accounts (id int PRIMARY KEY, owner text NOT NULL, "
        "balance numeric(12,2) NOT NULL) WITH (autovacuum_enabled = off)"
    )
    admin.run("INSERT INTO accounts VALUES (1, 'alice', 100)")

    print("\n=== 2.1 REPEATABLE READ: снимок берётся первым запросом и живёт до конца транзакции ===")
    a.run("BEGIN ISOLATION LEVEL REPEATABLE READ")
    a.run("SELECT balance FROM accounts WHERE id = 1")
    a.run("SELECT pg_current_snapshot()")
    # читающая транзакция XID не получает, номер выдаётся только при первой записи
    a.run("SELECT pg_current_xact_id_if_assigned()")
    b.run("BEGIN")
    # запись не ждёт читателя, у которого открыта транзакция на той же строке
    b.run("UPDATE accounts SET balance = 70 WHERE id = 1", timed=True)
    b.run("SELECT pg_current_xact_id()")
    # чтение не ждёт писателя, который держит блокировку строки
    a.run("SELECT balance FROM accounts WHERE id = 1", timed=True)
    b.run("COMMIT")
    # B зафиксирована, но её XID не меньше xmax снимка A: для A её изменения в будущем
    a.run("SELECT balance FROM accounts WHERE id = 1")
    a.run("SELECT pg_current_snapshot()")
    a.run("COMMIT")
    a.run("SELECT balance FROM accounts WHERE id = 1")

    print("\n=== 2.2 READ COMMITTED: новый снимок на каждый оператор ===")
    b.run("BEGIN")
    b.run("UPDATE accounts SET balance = 40 WHERE id = 1")
    b.run("SELECT pg_current_xact_id()")
    # посторонняя транзакция начинается после B и сразу фиксируется: xmax снимка уходит за B
    admin.run("SELECT pg_current_xact_id()")
    a.run("BEGIN ISOLATION LEVEL READ COMMITTED")
    # B в списке активных транзакций снимка (третье поле), её версию A не видит
    a.run("SELECT balance, pg_current_snapshot() FROM accounts WHERE id = 1")
    b.run("COMMIT")
    # та же транзакция A, следующий оператор: новый снимок, B в нём уже зафиксирована
    a.run("SELECT balance, pg_current_snapshot() FROM accounts WHERE id = 1")
    a.run("COMMIT")


VACUUM_LINES = ("tuples:", "removable cutoff:", "pages:")


def vacuum_verbose(s, table):
    s.notices.clear()
    s.run(f"VACUUM (VERBOSE) {table}")
    # из длинного отчёта оставляем строки про версии, горизонт и страницы самой таблицы,
    # отчёт по её TOAST-таблице пропускаем
    for msg in s.notices:
        lines = msg.splitlines()
        if not lines or f'.public.{table}"' not in lines[0] or len(lines) == 1:
            continue
        for line in lines[1:]:
            if line.strip().startswith(VACUUM_LINES):
                print(f"      INFO {line.strip()}")


def table_state(s, table):
    # статистика сессии уходит в общую память, когда сессия простаивает: просим сделать это сразу
    s.run("SELECT pg_stat_force_next_flush()")
    s.run(
        "SELECT n_live_tup, n_dead_tup, pg_size_pretty(pg_relation_size(relid)) AS size "
        f"FROM pg_stat_user_tables WHERE relname = '{table}'"
    )


def horizon(admin, h, w):
    admin.run("DROP TABLE IF EXISTS events CASCADE")
    admin.run(
        "CREATE TABLE events (id int PRIMARY KEY, payload text NOT NULL) "
        "WITH (autovacuum_enabled = off)"
    )
    admin.run("INSERT INTO events SELECT g, md5(g::text) FROM generate_series(1, 100000) g")
    # без сброса счётчики INSERT дойдут до общей памяти после VACUUM и удвоят n_live_tup
    admin.run("SELECT pg_stat_force_next_flush()")
    admin.run("VACUUM events")
    table_state(admin, "events")

    print("\n=== 4.1 открытая транзакция H держит снимок, W переписывает всю таблицу ===")
    h.run("BEGIN ISOLATION LEVEL REPEATABLE READ")
    h.run("SELECT count(*) FROM events")
    w.run("UPDATE events SET payload = upper(payload)")
    # так выглядит виновник в мониторинге: простаивает внутри транзакции и держит backend_xmin
    admin.run(
        "SELECT application_name, state, backend_xmin, "
        "age(backend_xmin) AS xmin_age FROM pg_stat_activity "
        "WHERE backend_xmin IS NOT NULL AND pid <> pg_backend_pid() ORDER BY backend_start"
    )
    vacuum_verbose(w, "events")
    table_state(admin, "events")

    print("\n=== 4.2 H завершилась: тот же VACUUM удаляет мёртвые версии ===")
    h.run("COMMIT")
    vacuum_verbose(w, "events")
    # место внутри файла освободилось для новых версий, но сам файл не уменьшился
    table_state(admin, "events")

    print("\n=== 4.3 VACUUM FULL переписывает таблицу в новый файл ===")
    admin.run("SELECT pg_relation_filenode('events')")
    admin.run("VACUUM FULL events")
    admin.run("SELECT pg_relation_filenode('events'), pg_size_pretty(pg_relation_size('events'))")


SCENARIOS = {"snapshot": snapshot, "horizon": horizon}


def main(names):
    if names == ["all"]:
        names = list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if not names or unknown:
        sys.exit(f"использование: {sys.argv[0]} all|snapshot|horizon")
    for name in names:
        sessions = [Session("admin"), Session("A" if name == "snapshot" else "H"),
                    Session("B" if name == "snapshot" else "W")]
        # имя сессии видно в pg_stat_activity.application_name
        for s in sessions:
            s.conn.execute(f"SET application_name = 'session_{s.name}'")
        try:
            SCENARIOS[name](*sessions)
        finally:
            for s in sessions:
                s.close()


if __name__ == "__main__":
    main(sys.argv[1:])
