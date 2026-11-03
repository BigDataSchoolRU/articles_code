# postgres 18.6 + psycopg 3.3.7, прогнано на стенде 2026-11-03
"""Повторная загрузка одной партиции тремя способами.

Задача грузит продажи за день. Первая попытка падает на середине, планировщик
делает ретрай, потом задачу ещё раз перезапускают руками. Смотрим, что остаётся
в целевой таблице при наивном INSERT, при перезаписи партиции и при upsert.
"""
import os

import psycopg

DSN = os.environ.get("PG_DSN", "postgresql://demo:demo@127.0.0.1:55432/idem")
DAY = "2026-11-01"

# Источник: пять заказов за день. order_id это естественный ключ строки.
BATCH = [
    (101, DAY, 1200.00),
    (102, DAY, 350.50),
    (103, DAY, 990.00),
    (104, DAY, 75.25),
    (105, DAY, 4100.00),
]


class TaskCrash(Exception):
    """Имитация падения задачи посреди загрузки."""


def setup(conn):
    with conn.cursor() as cur:
        for name in ("sales_naive", "sales_overwrite", "sales_upsert"):
            cur.execute(f"DROP TABLE IF EXISTS {name}")
            # первичный ключ есть только у таблицы для upsert: он и будет арбитром
            pk = "PRIMARY KEY" if name == "sales_upsert" else ""
            cur.execute(
                f"CREATE TABLE {name} (order_id int {pk}, sale_date date, amount numeric(12,2))"
            )
    conn.commit()


def load_naive(conn, crash_after=None):
    """INSERT строка за строкой с автокоммитом, как пишет наивный скрипт."""
    with conn.cursor() as cur:
        for i, row in enumerate(BATCH, 1):
            cur.execute("INSERT INTO sales_naive VALUES (%s, %s, %s)", row)
            conn.commit()
            if crash_after and i == crash_after:
                raise TaskCrash(f"упали после {i} строк")


def load_overwrite(conn, crash_after=None):
    """Перезапись партиции: DELETE за день и INSERT в одной транзакции."""
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sales_overwrite WHERE sale_date = %s", (DAY,))
            for i, row in enumerate(BATCH, 1):
                cur.execute("INSERT INTO sales_overwrite VALUES (%s, %s, %s)", row)
                if crash_after and i == crash_after:
                    raise TaskCrash(f"упали после {i} строк")
        conn.commit()
    except TaskCrash:
        conn.rollback()  # транзакция не дошла до COMMIT, в таблице ничего не осталось
        raise


def load_upsert(conn, only_changed=True):
    """INSERT ... ON CONFLICT по первичному ключу. Возвращает число затронутых строк."""
    sql = """
        INSERT INTO sales_upsert AS t (order_id, sale_date, amount)
        VALUES (%s, %s, %s)
        ON CONFLICT (order_id) DO UPDATE
        SET sale_date = excluded.sale_date, amount = excluded.amount
    """
    if only_changed:
        # без этого условия повтор переписывает каждую строку, хоть и теми же значениями
        sql += " WHERE (t.sale_date, t.amount) IS DISTINCT FROM (excluded.sale_date, excluded.amount)"
    touched = 0
    with conn.cursor() as cur:
        for row in BATCH:
            cur.execute(sql, row)
            touched += cur.rowcount
    conn.commit()
    return touched


def state(conn, table):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT order_id), coalesce(sum(amount), 0) FROM {table}")
        rows, uniq, total = cur.fetchone()
    return f"строк={rows} уникальных order_id={uniq} сумма={total}"


def run_attempts(conn, name, attempt):
    """Попытка 1 падает после 3 строк, попытка 2 это ретрай, попытка 3 ручной перезапуск."""
    print(f"\n--- {name} ---")
    for n, crash in ((1, 3), (2, None), (3, None)):
        try:
            attempt(conn, crash)
            note = "успех"
        except TaskCrash as e:
            note = str(e)
        print(f"попытка {n}: {note:<20} {state(conn, name)}")


def main():
    with psycopg.connect(DSN) as conn:
        print("server_version:", conn.info.parameter_status("server_version"))
        print("psycopg:", psycopg.__version__)
        setup(conn)

        run_attempts(conn, "sales_naive", load_naive)
        run_attempts(conn, "sales_overwrite", load_overwrite)

        # upsert работает построчно по ключу, поэтому падение на середине ему не страшно,
        # повтор просто дописывает недостающее и не трогает уже загруженное
        print("\n--- sales_upsert ---")
        for n, only_changed in ((1, True), (2, True), (3, False)):
            touched = load_upsert(conn, only_changed)
            mode = "WHERE IS DISTINCT FROM" if only_changed else "без WHERE"
            print(f"попытка {n} ({mode}): затронуто строк={touched}  {state(conn, 'sales_upsert')}")

        # граница upsert: одна команда не может обновить одну строку дважды
        print("\n--- дубль ключа внутри одной пачки ---")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sales_upsert VALUES (106, %s, 10), (106, %s, 20)
                       ON CONFLICT (order_id) DO UPDATE SET amount = excluded.amount""",
                    (DAY, DAY),
                )
            conn.commit()
        except psycopg.Error as e:
            conn.rollback()
            print(f"{type(e).__name__}: {e.diag.message_primary}")
            print(f"hint: {e.diag.message_hint}")


if __name__ == "__main__":
    main()
