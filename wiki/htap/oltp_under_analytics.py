# PostgreSQL 18.4 (Homebrew), psycopg 3.3.4, Python 3.12.13, прогнано на стенде 2026-08-24
"""
Демо 1 к статье про HTAP: что происходит с транзакционной нагрузкой, когда
аналитические запросы идут по той же таблице того же строкового хранилища.

Сценарий: таблица заказов на 5 млн строк. Сначала меряем латентность точечных
UPDATE по первичному ключу в тишине, потом повторяем тот же замер, пока три
параллельных соединения крутят тяжёлую агрегацию по всей таблице.
"""

import os
import statistics
import threading
import time

import psycopg

DSN = os.environ.get("HTAP_DSN", "dbname=htap_demo")
ROWS = 12_000_000         # размер демо-таблицы: заведомо больше shared_buffers
UPDATES = 300             # сколько точечных UPDATE в каждой фазе замера
ANALYTIC_WORKERS = 6      # сколько параллельных аналитических соединений
WARMUP = 50               # холостые UPDATE до замера, чтобы не мерить холодный кэш


def num(n):
    """Разряды пробелом: 5 000 000 читается глазами лучше, чем 5000000."""
    return f"{n:,}".replace(",", "\u00a0")


# Аналитический запрос: агрегация по всей таблице с сотнями тысяч групп. Индекс тут
# не помогает, планировщик читает все строки подряд, а хэш-таблица группировки не
# влезает в work_mem и выплёскивается на диск.
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


def ensure_orders(conn):
    """Создаёт и наполняет таблицу заказов, если её ещё нет."""
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.orders')")
        if cur.fetchone()[0] is not None:
            cur.execute("select count(*) from orders")
            print("таблица orders уже есть, строк: " + num(cur.fetchone()[0]))
            return
        print("создаю orders на " + num(ROWS) + " строк")
        t0 = time.perf_counter()
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
        print(f"наполнение заняло {time.perf_counter() - t0:.1f} с")


def table_size(conn):
    with conn.cursor() as cur:
        cur.execute("select pg_size_pretty(pg_total_relation_size('orders'))")
        return cur.fetchone()[0]


def measure_updates(dsn, n, tag):
    """Меряет латентность n точечных UPDATE по первичному ключу, каждый со своим commit."""
    lat = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Прогрев: первые обращения тянут страницы с диска и открывают соединение,
            # без него первая фаза мерила бы холодный старт, а не саму нагрузку.
            for i in range(WARMUP):
                cur.execute("update orders set amount = amount where id = %s",
                            (1 + (i * 104729) % ROWS,))
                conn.commit()
            for i in range(n):
                # id разбросаны по всей таблице, чтобы не попадать в один и тот же блок
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
    print(f"[{tag}] UPDATE x{n}: p50 {p50:.2f} мс, p95 {p95:.2f} мс, max {lat[-1]:.2f} мс")
    return p50, p95


def analytic_loop(dsn, stop_event, results, idx):
    """Крутит аналитический запрос, пока не попросят остановиться."""
    times = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            while not stop_event.is_set():
                t0 = time.perf_counter()
                cur.execute(ANALYTIC_SQL)
                cur.fetchall()
                times.append(time.perf_counter() - t0)
    results[idx] = times


def main():
    with psycopg.connect(DSN) as conn:
        ensure_orders(conn)
        print(f"размер таблицы в строковом хранилище: {table_size(conn)}")

    # Одиночный замер аналитики без конкурентов: точка отсчёта для второй фазы.
    # Первый прогон греет кэш и в зачёт не идёт, засчитывается второй.
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(ANALYTIC_SQL)
            cur.fetchall()
            t0 = time.perf_counter()
            cur.execute(ANALYTIC_SQL)
            rows = cur.fetchall()
            solo = time.perf_counter() - t0
    print(f"аналитический запрос в одиночку: {solo:.2f} с, строк в ответе: {len(rows)}")

    print("\n--- фаза 1: только транзакционная нагрузка ---")
    base_p50, base_p95 = measure_updates(DSN, UPDATES, "тишина")

    print(f"\n--- фаза 2: те же UPDATE под {ANALYTIC_WORKERS} параллельными агрегациями ---")
    stop = threading.Event()
    results = [None] * ANALYTIC_WORKERS
    workers = [
        threading.Thread(target=analytic_loop, args=(DSN, stop, results, i))
        for i in range(ANALYTIC_WORKERS)
    ]
    for w in workers:
        w.start()
    time.sleep(3)  # даём аналитике реально начать читать таблицу
    load_p50, load_p95 = measure_updates(DSN, UPDATES, "под нагрузкой")
    stop.set()
    for w in workers:
        w.join()

    done = [t for times in results if times for t in times]
    if done:
        print(f"аналитических запросов прошло: {len(done)}, "
              f"среднее время {statistics.mean(done):.2f} с против {solo:.2f} с в одиночку")

    print("\n--- итог ---")
    print(f"p50 латентности UPDATE: {base_p50:.2f} -> {load_p50:.2f} мс "
          f"(x{load_p50 / base_p50:.1f})")
    print(f"p95 латентности UPDATE: {base_p95:.2f} -> {load_p95:.2f} мс "
          f"(x{load_p95 / base_p95:.1f})")


if __name__ == "__main__":
    main()
