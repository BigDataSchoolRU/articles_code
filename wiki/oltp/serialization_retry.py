# PostgreSQL 18.6 (postgres:18.6), psycopg 3.3.7, прогнано на стенде 2026-11-03
"""Две конкурирующие OLTP-транзакции на PostgreSQL.

Сценарий 1. Потерянное обновление (lost update): приложение читает баланс и пишет
вычисленное значение. На READ COMMITTED одно списание пропадает, на REPEATABLE READ
вторая транзакция получает SQLSTATE 40001 и повторяется целиком.

Сценарий 2. Перекос записи (write skew): две транзакции читают общее условие и меняют
разные строки. REPEATABLE READ его пропускает, SERIALIZABLE (SSI) ловит без блокировок.
"""
import os

import psycopg
from psycopg import errors

DSN = os.environ.get("PG_DSN", "postgresql://demo:demo@127.0.0.1:55433/oltp")


def connect():
    # autocommit=True: границы транзакций задаём сами командами BEGIN и COMMIT
    return psycopg.connect(DSN, autocommit=True)


def reset(conn):
    conn.execute("DROP TABLE IF EXISTS accounts, doctors")
    conn.execute("CREATE TABLE accounts (id int PRIMARY KEY, balance int NOT NULL)")
    conn.execute("INSERT INTO accounts VALUES (1, 1000)")
    conn.execute("CREATE TABLE doctors (name text PRIMARY KEY, on_call bool NOT NULL)")
    conn.execute("INSERT INTO doctors VALUES ('alice', true), ('bob', true)")


def balance(conn):
    return conn.execute("SELECT balance FROM accounts WHERE id = 1").fetchone()[0]


def withdraw(conn, amount):
    # чтение и запись разнесены, как в типичном коде приложения
    current = balance(conn)
    conn.execute("UPDATE accounts SET balance = %s WHERE id = 1", (current - amount,))
    return current


def lost_update(level):
    print(f"\n--- сценарий 1, {level}: два списания по 100 с баланса 1000 ---")
    admin, t1, t2 = connect(), connect(), connect()
    reset(admin)

    # T1 начинает и читает баланс, но запись пока не делает
    t1.execute(f"BEGIN ISOLATION LEVEL {level}")
    seen = balance(t1)
    print(f"T1 прочитала баланс {seen}")

    # T2 успевает целиком: прочитать, списать 100 и зафиксироваться
    t2.execute(f"BEGIN ISOLATION LEVEL {level}")
    withdraw(t2, 100)
    t2.execute("COMMIT")
    print(f"T2 списала 100 и сделала COMMIT, в базе {balance(admin)}")

    # T1 пишет значение, вычисленное из своего чтения
    attempt = 1
    while True:
        try:
            if attempt > 1:
                t1.execute(f"BEGIN ISOLATION LEVEL {level}")
                seen = balance(t1)
            t1.execute("UPDATE accounts SET balance = %s WHERE id = 1", (seen - 100,))
            t1.execute("COMMIT")
            print(f"T1 попытка {attempt}: записала {seen - 100}, COMMIT")
            break
        except errors.SerializationFailure as e:
            # 40001: повторять нужно всю транзакцию с чтением, а не один UPDATE
            t1.execute("ROLLBACK")
            print(f"T1 попытка {attempt}: SQLSTATE {e.sqlstate} {e.diag.message_primary}")
            attempt += 1

    print(f"итог: баланс {balance(admin)}, ожидалось 800")
    for c in (admin, t1, t2):
        c.close()


def go_off_call(conn, name):
    # правило: уйти с дежурства можно, только если дежурит хотя бы ещё один врач
    on_call = conn.execute("SELECT count(*) FROM doctors WHERE on_call").fetchone()[0]
    if on_call >= 2:
        conn.execute("UPDATE doctors SET on_call = false WHERE name = %s", (name,))
    return on_call


def write_skew(level):
    print(f"\n--- сценарий 2, {level}: alice и bob одновременно уходят с дежурства ---")
    admin, t1, t2 = connect(), connect(), connect()
    reset(admin)

    t1.execute(f"BEGIN ISOLATION LEVEL {level}")
    t2.execute(f"BEGIN ISOLATION LEVEL {level}")
    # обе транзакции видят двух дежурных и меняют разные строки, блокировок друг на друга нет
    print(f"T1 (alice) видит дежурных: {go_off_call(t1, 'alice')}")
    print(f"T2 (bob) видит дежурных: {go_off_call(t2, 'bob')}")

    for tag, conn in (("T1", t1), ("T2", t2)):
        try:
            conn.execute("COMMIT")
            print(f"{tag}: COMMIT прошёл")
        except errors.SerializationFailure as e:
            conn.execute("ROLLBACK")
            print(f"{tag}: SQLSTATE {e.sqlstate} {e.diag.message_primary}")
            print(f"{tag}: detail {e.diag.message_detail}")

    left = admin.execute("SELECT count(*) FROM doctors WHERE on_call").fetchone()[0]
    print(f"итог: дежурных {left}, правило требует не меньше 1")
    for c in (admin, t1, t2):
        c.close()


if __name__ == "__main__":
    with connect() as c:
        print("server_version:", c.execute("SHOW server_version").fetchone()[0])
        print("default_transaction_isolation:",
              c.execute("SHOW default_transaction_isolation").fetchone()[0])
    print("psycopg:", psycopg.__version__)

    lost_update("READ COMMITTED")
    lost_update("REPEATABLE READ")
    write_skew("REPEATABLE READ")
    write_skew("SERIALIZABLE")
