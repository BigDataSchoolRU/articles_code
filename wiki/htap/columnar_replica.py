# PostgreSQL 18.4 (Homebrew), DuckDB 1.5.5, psycopg 3.3.4, Python 3.12.13, прогнано на стенде 2026-08-24
"""
Демо 2 к статье про HTAP: то же самое, но аналитика уходит в колоночную реплику.

Это ручная сборка того, что HTAP-системы вроде TiDB с TiFlash или AlloyDB делают
внутри себя: строковое хранилище держит транзакции, колоночная копия тех же строк
отвечает на агрегации, между ними асинхронная репликация с ненулевым окном лага.

Меряем четыре вещи:
  1. сколько стоит первичная заливка колоночной копии;
  2. во что превращается тот же аналитический запрос на колоночном хранении;
  3. что происходит с латентностью UPDATE, когда аналитика съехала с базы;
  4. какое окно рассинхрона даёт догрузка дельты.
"""

import os
import statistics
import threading
import time

import duckdb
import psycopg

DSN = os.environ.get("HTAP_DSN", "dbname=htap_demo")
ROWS = 12_000_000
UPDATES = 300
WARMUP = 50                  # холостые UPDATE до замера, чтобы не мерить холодный кэш
NEW_ORDERS = 20_000          # размер дельты для замера лага репликации
DUCK_PATH = "orders_columnar.duckdb"
CSV_PATH = "orders_snapshot.csv"

# Тот же самый запрос, что и в демо 1: сравнение честное только на одинаковом SQL.
ANALYTIC_SQL = """
select customer_id,
       status,
       count(*)     as cnt,
       sum(amount)  as revenue,
       avg(amount)  as avg_check
from orders
group by 1, 2
order by revenue desc
limit 20
"""

def num(n):
    """Разряды пробелом: 5 000 000 читается глазами лучше, чем 5000000."""
    return f"{n:,}".replace(",", "\u00a0")

COLUMNS = {
    "id": "BIGINT",
    "customer_id": "INTEGER",
    "status": "VARCHAR",
    "amount": "DECIMAL(10,2)",
    "created_at": "TIMESTAMPTZ",
}


def ensure_orders(conn):
    """Создаёт и наполняет таблицу заказов в PostgreSQL, если её ещё нет."""
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.orders')")
        if cur.fetchone()[0] is not None:
            return
        cur.execute("""
            create table orders (
                id          bigint primary key,
                customer_id integer      not null,
                status      text         not null,
                amount      numeric(10,2) not null,
                created_at  timestamptz  not null
            )
        """)
        cur.execute("""
            insert into orders (id, customer_id, status, amount, created_at)
            select g,
                   (random() * 100000)::int,
                   (array['new','paid','shipped','done','cancelled'])[1 + floor(random() * 5)],
                   (random() * 10000)::numeric(10,2),
                   now() - ((random() * 365)::int) * interval '1 day'
            from generate_series(1, %s) g
        """, (ROWS,))
        conn.commit()
        cur.execute("analyze orders")
        conn.commit()


def dump_to_csv(conn, path, where="true"):
    """Выгружает строки из PostgreSQL в CSV. Это наш примитивный канал репликации."""
    sql = (f"copy (select id, customer_id, status, amount, created_at "
           f"from orders where {where} order by id) to stdout (format csv, header true)")
    with open(path, "wb") as f:
        with conn.cursor() as cur:
            with cur.copy(sql) as copy:
                for chunk in copy:
                    f.write(chunk)
    return os.path.getsize(path)


def initial_load(pg, duck):
    """Первичная заливка колоночной копии: снимок всей таблицы."""
    t0 = time.perf_counter()
    size = dump_to_csv(pg, CSV_PATH)
    t_dump = time.perf_counter() - t0

    t1 = time.perf_counter()
    duck.execute("drop table if exists orders")
    duck.execute(
        "create table orders as select * from read_csv(?, header=true, columns=?)",
        [CSV_PATH, COLUMNS],
    )
    t_load = time.perf_counter() - t1

    cnt = duck.execute("select count(*) from orders").fetchone()[0]
    print(f"первичная заливка: выгрузка {t_dump:.1f} с, загрузка в колоночное {t_load:.1f} с, "
          f"всего {t_dump + t_load:.1f} с, строк " + num(cnt))
    print(f"размер CSV-снимка: {size / 1024 / 1024:.0f} МБ")
    os.remove(CSV_PATH)  # снимок больше не нужен, а место на диске занимает


def measure_updates(dsn, n, tag):
    """Меряет латентность точечных UPDATE по первичному ключу."""
    lat = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for i in range(WARMUP):  # прогрев, в замер не идёт
                cur.execute("update orders set amount = amount where id = %s",
                            (1 + (i * 104729) % ROWS,))
                conn.commit()
            for i in range(n):
                row_id = 1 + (i * 7919) % ROWS
                t0 = time.perf_counter()
                cur.execute(
                    "update orders set status = 'paid', amount = amount + 0.01 where id = %s",
                    (row_id,),
                )
                conn.commit()
                lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    p50 = statistics.median(lat)
    p95 = lat[int(len(lat) * 0.95) - 1]
    print(f"[{tag}] UPDATE x{n}: p50 {p50:.2f} мс, p95 {p95:.2f} мс")
    return p50, p95


def duck_analytic_loop(path, stop_event, holder):
    """Крутит аналитику в колоночной копии своим соединением, пока не попросят стоп."""
    times = []
    con = duckdb.connect(path, read_only=True)
    while not stop_event.is_set():
        t0 = time.perf_counter()
        con.execute(ANALYTIC_SQL).fetchall()
        times.append(time.perf_counter() - t0)
    con.close()
    holder.extend(times)


def main():
    for junk in (DUCK_PATH, DUCK_PATH + ".wal", CSV_PATH):
        if os.path.exists(junk):
            os.remove(junk)

    pg = psycopg.connect(DSN)
    ensure_orders(pg)

    with pg.cursor() as cur:
        cur.execute("select pg_size_pretty(pg_total_relation_size('orders')), count(*) from orders")
        pg_size, pg_rows = cur.fetchone()
    print("строковое хранилище: " + num(pg_rows) + f" строк, {pg_size}")

    duck = duckdb.connect(DUCK_PATH)
    duck.execute("set threads to 4")

    print("\n--- шаг 1: первичная репликация в колоночное хранилище ---")
    initial_load(pg, duck)
    duck.close()
    duck_size = os.path.getsize(DUCK_PATH)
    print(f"размер колоночного файла: {duck_size / 1024 / 1024:.0f} МБ "
          f"против {pg_size} в строковом")

    print("\n--- шаг 2: один и тот же запрос в двух представлениях ---")
    with pg.cursor() as cur:
        cur.execute(ANALYTIC_SQL)   # прогрев кэша, в зачёт не идёт
        cur.fetchall()
        t0 = time.perf_counter()
        cur.execute(ANALYTIC_SQL)
        pg_rows_out = cur.fetchall()
        t_pg = time.perf_counter() - t0
    print(f"строковое хранилище: {t_pg:.2f} с, строк в ответе {len(pg_rows_out)}")

    con = duckdb.connect(DUCK_PATH, read_only=True)
    con.execute("set threads to 4")
    con.execute(ANALYTIC_SQL).fetchall()   # прогрев, в зачёт не идёт
    t0 = time.perf_counter()
    duck_rows_out = con.execute(ANALYTIC_SQL).fetchall()
    t_duck = time.perf_counter() - t0
    con.close()
    print(f"колоночное хранилище: {t_duck:.2f} с, строк в ответе {len(duck_rows_out)}")
    print(f"разница по времени: {t_pg / t_duck:.1f}x")

    print(f"\n--- шаг 3: UPDATE в базе, пока аналитика идёт в колоночной копии ---")
    stop = threading.Event()
    times = []
    w = threading.Thread(target=duck_analytic_loop, args=(DUCK_PATH, stop, times))
    w.start()
    time.sleep(1)
    measure_updates(DSN, UPDATES, "аналитика в реплике")
    stop.set()
    w.join()
    if times:
        print(f"аналитических запросов в реплике за это время: {len(times)}, "
              f"среднее {statistics.mean(times) * 1000:.0f} мс")

    print("\n--- шаг 4: окно лага, догрузка дельты в " + num(NEW_ORDERS) + " заказов ---")
    with pg.cursor() as cur:
        cur.execute("select max(id) from orders")
        max_id = cur.fetchone()[0]
        cur.execute("""
            insert into orders (id, customer_id, status, amount, created_at)
            select %s + g,
                   (random() * 100000)::int,
                   'new',
                   (random() * 10000)::numeric(10,2),
                   now()
            from generate_series(1, %s) g
        """, (max_id, NEW_ORDERS))
    pg.commit()
    t_insert = time.time()

    # Реплика этих строк ещё не видит: до догрузки аналитика отвечает по старым данным.
    con = duckdb.connect(DUCK_PATH)
    stale = con.execute("select count(*) from orders").fetchone()[0]
    print("в базе строк " + num(pg_rows + NEW_ORDERS)
          + ", в колоночной копии пока " + num(stale))

    t0 = time.perf_counter()
    delta_path = "orders_delta.csv"
    size = dump_to_csv(pg, delta_path, where=f"id > {max_id}")
    con.execute(
        "insert into orders select * from read_csv(?, header=true, columns=?)",
        [delta_path, COLUMNS],
    )
    t_delta = time.perf_counter() - t0
    fresh = con.execute("select count(*) from orders").fetchone()[0]
    con.close()
    os.remove(delta_path)

    print(f"догрузка дельты: {t_delta:.2f} с ({size / 1024:.0f} КБ), "
          "в реплике стало " + num(fresh) + " строк")
    print(f"окно рассинхрона от коммита до видимости в аналитике: "
          f"{time.time() - t_insert:.2f} с")

    pg.close()


if __name__ == "__main__":
    main()
