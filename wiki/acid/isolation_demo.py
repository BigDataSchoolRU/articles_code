# psycopg 3.3.8, postgres 18.6 в Docker, прогнано на стенде 2026-11-05
"""Изоляция транзакций в PostgreSQL на двух сессиях с явным чередованием шагов.

Каждый шаг выполняется по очереди, а не наперегонки, поэтому аномалии воспроизводятся
детерминированно, без зависимости от таймингов.

    python isolation_demo.py all          # все сценарии
    python isolation_demo.py reads lost_update   # несколько сценариев за один запуск
    python isolation_demo.py reads        # грязное, неповторяемое и фантомное чтение
    python isolation_demo.py lost_update  # потерянное обновление на RC и RR
    python isolation_demo.py write_skew   # write skew на RR и SERIALIZABLE, повтор по 40001

Адрес сервера берётся из ACID_DSN, по умолчанию локальный контейнер из docker-compose.yml.
"""
import os
import sys
from decimal import Decimal

import psycopg

sys.stdout.reconfigure(line_buffering=True)

DSN = os.environ.get(
    "ACID_DSN", "host=127.0.0.1 port=55435 dbname=acid user=demo password=demo"
)


def fmt(value):
    """Decimal и прочее печатаем как в psql, без обёрток Python."""
    return value if isinstance(value, (int, bool)) or value is None else str(value)


class Session:
    """Одна сессия PostgreSQL. autocommit=True, чтобы BEGIN и COMMIT были видны явно."""

    def __init__(self, name):
        self.name = name
        self.conn = psycopg.connect(DSN, autocommit=True)

    def run(self, sql, params=None):
        # в лог идёт запрос с подставленными значениями, на сервер уходят параметры отдельно
        shown = sql % tuple(f"'{p}'" if isinstance(p, str) else str(p) for p in params) if params else sql
        print(f"[{self.name}] {shown}")
        try:
            cur = self.conn.execute(sql, params)
        except psycopg.Error as e:
            # SQLSTATE и класс исключения psycopg: по ним приложение решает, повторять ли
            print(f"      !! SQLSTATE {e.sqlstate} {type(e).__name__}: {e.diag.message_primary}")
            return e
        if cur.description:
            rows = [tuple(fmt(v) for v in row) for row in cur.fetchall()]
            print(f"      -> {rows}")
            return rows
        return None

    def close(self):
        self.conn.close()


def setup(admin):
    admin.run("DROP TABLE IF EXISTS accounts, doctors CASCADE")
    admin.run(
        "CREATE TABLE accounts (id int PRIMARY KEY, owner text NOT NULL, "
        "balance numeric(12,2) NOT NULL)"
    )
    admin.run("CREATE TABLE doctors (name text PRIMARY KEY, on_call boolean NOT NULL)")


def reset_accounts(admin):
    admin.run("TRUNCATE accounts")
    admin.run("INSERT INTO accounts VALUES (1, 'alice', 100), (2, 'bob', 50)")


def reads(admin, a, b):
    """Чтения внутри транзакции A, пока B меняет данные."""
    print("\n=== 3.1 Грязное чтение: READ UNCOMMITTED в PostgreSQL ведёт себя как READ COMMITTED ===")
    reset_accounts(admin)
    b.run("BEGIN")
    b.run("UPDATE accounts SET balance = 0 WHERE id = 1")
    a.run("BEGIN ISOLATION LEVEL READ UNCOMMITTED")
    a.run("SHOW transaction_isolation")
    a.run("SELECT balance FROM accounts WHERE id = 1")
    a.run("COMMIT")
    b.run("ROLLBACK")

    for level in ("READ COMMITTED", "REPEATABLE READ"):
        print(f"\n=== 3.2 Неповторяемое и фантомное чтение на {level} ===")
        reset_accounts(admin)
        a.run(f"BEGIN ISOLATION LEVEL {level}")
        a.run("SELECT balance FROM accounts WHERE id = 1")
        a.run("SELECT count(*) FROM accounts WHERE balance >= 50")
        # B меняет строку и добавляет новую, подходящую под условие A, и фиксирует
        b.run("UPDATE accounts SET balance = balance - 30 WHERE id = 1")
        b.run("INSERT INTO accounts VALUES (3, 'carol', 500)")
        a.run("SELECT balance FROM accounts WHERE id = 1")
        a.run("SELECT count(*) FROM accounts WHERE balance >= 50")
        a.run("COMMIT")


def lost_update(admin, a, b):
    """Чтение, вычисление в приложении, запись: классическое потерянное обновление."""
    for level in ("READ COMMITTED", "REPEATABLE READ"):
        print(f"\n=== 3.3 Потерянное обновление на {level}: A кладёт +10, B кладёт +20 ===")
        reset_accounts(admin)
        a.run(f"BEGIN ISOLATION LEVEL {level}")
        b.run(f"BEGIN ISOLATION LEVEL {level}")
        bal_a = a.run("SELECT balance FROM accounts WHERE id = 1")[0][0]
        bal_b = b.run("SELECT balance FROM accounts WHERE id = 1")[0][0]
        # новое значение посчитано в приложении по прочитанному, а не выражением в SQL
        a.run("UPDATE accounts SET balance = %s WHERE id = 1", (Decimal(bal_a) + 10,))
        a.run("COMMIT")
        res = b.run("UPDATE accounts SET balance = %s WHERE id = 1", (Decimal(bal_b) + 20,))
        if isinstance(res, psycopg.errors.SerializationFailure):
            b.run("ROLLBACK")
            # повтор транзакции целиком: новый снимок, новое чтение, новая запись
            print("      .. повтор транзакции B целиком")
            b.run(f"BEGIN ISOLATION LEVEL {level}")
            bal_b = b.run("SELECT balance FROM accounts WHERE id = 1")[0][0]
            b.run("UPDATE accounts SET balance = %s WHERE id = 1", (Decimal(bal_b) + 20,))
        b.run("COMMIT")
        admin.run("SELECT balance AS final_balance FROM accounts WHERE id = 1")


def go_off_duty(s, name):
    """Врач уходит с дежурства, только если на дежурстве останется хотя бы один."""
    on_call = s.run("SELECT count(*) FROM doctors WHERE on_call")[0][0]
    if on_call >= 2:
        return s.run("UPDATE doctors SET on_call = false WHERE name = %s", (name,))
    print(f"      .. {name} остаётся: на дежурстве {on_call}")
    return None


def write_skew(admin, a, b):
    """Инвариант «на дежурстве хотя бы один врач» не выражен ограничением схемы."""
    for level in ("REPEATABLE READ", "SERIALIZABLE"):
        print(f"\n=== 4. Write skew на {level}: alice и bob одновременно уходят с дежурства ===")
        admin.run("TRUNCATE doctors")
        admin.run("INSERT INTO doctors VALUES ('alice', true), ('bob', true)")
        a.run(f"BEGIN ISOLATION LEVEL {level}")
        b.run(f"BEGIN ISOLATION LEVEL {level}")
        go_off_duty(a, "alice")
        res_update = go_off_duty(b, "bob")
        if level == "SERIALIZABLE":
            # предикатные блокировки SSI: ничего не блокируют, только фиксируют, кто что читал
            admin.run(
                "SELECT CASE l.pid WHEN %s THEN 'A' WHEN %s THEN 'B' END AS session, "
                "l.locktype, c.relname, l.mode "
                "FROM pg_locks l LEFT JOIN pg_class c ON c.oid = l.relation "
                "WHERE l.mode = 'SIReadLock' ORDER BY l.pid, c.relname",
                (a.conn.info.backend_pid, b.conn.info.backend_pid),
            )
        a.run("COMMIT")
        res = b.run("COMMIT")
        failure = psycopg.errors.SerializationFailure
        if isinstance(res, failure) or isinstance(res_update, failure):
            print("      .. повтор транзакции B целиком")
            b.run(f"BEGIN ISOLATION LEVEL {level}")
            go_off_duty(b, "bob")
            b.run("COMMIT")
        admin.run("SELECT name, on_call FROM doctors ORDER BY name")
        admin.run("SELECT count(*) FILTER (WHERE on_call) AS on_call_now FROM doctors")


def main():
    what = sys.argv[1:] or ["all"]
    scenarios = {"reads": reads, "lost_update": lost_update, "write_skew": write_skew}
    if what != ["all"] and not set(what) <= set(scenarios):
        print(f"использование: {sys.argv[0]} all|{'|'.join(scenarios)}", file=sys.stderr)
        return 2
    admin, a, b = Session("admin"), Session("A"), Session("B")
    try:
        admin.run("SHOW default_transaction_isolation")
        admin.run("SHOW max_pred_locks_per_transaction")
        setup(admin)
        for name, fn in scenarios.items():
            if what == ["all"] or name in what:
                fn(admin, a, b)
    finally:
        for s in (admin, a, b):
            s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
