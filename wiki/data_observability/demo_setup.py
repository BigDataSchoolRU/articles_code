# PostgreSQL 18.4, psycopg 3.3.4, прогнано на стенде 2026-08-25
# Готовит демо-витрину заказов: 30 дней ровной истории плюс текущий день.
# Это опорное состояние, от которого дальше считается базовая линия.

import psycopg
from datetime import datetime, timedelta, timezone

DSN_ADMIN = "postgresql:///postgres"
DSN = "postgresql:///observability_demo"
DAYS = 30                 # длина истории
ROWS_PER_DAY = 500        # ровный дневной объём
# Точка отсчёта — реальное текущее время: проверка свежести сравнивает с ним.
NOW = datetime.now(timezone.utc)


def recreate_database() -> None:
    """Пересоздаём базу с нуля, чтобы прогон был воспроизводимым."""
    with psycopg.connect(DSN_ADMIN, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS observability_demo WITH (FORCE)")
        conn.execute("CREATE DATABASE observability_demo")


def create_schema() -> None:
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("""
            CREATE TABLE orders (
                id          bigserial PRIMARY KEY,
                customer_id integer     NOT NULL,
                amount      numeric(10,2) NOT NULL,
                status      text        NOT NULL,
                created_at  timestamptz NOT NULL
            )
        """)
        # Таблица истории метрик. Именно она отличает наблюдаемость от разовых
        # тестов: у каждой метрики есть ряд значений во времени.
        conn.execute("""
            CREATE TABLE metric_history (
                id          bigserial PRIMARY KEY,
                scan_ts     timestamptz NOT NULL,
                dataset     text        NOT NULL,
                metric      text        NOT NULL,
                value       double precision NOT NULL
            )
        """)


def fill_history() -> None:
    """Наполняем 30 дней ровным потоком заказов с лёгким разбросом."""
    rows = []
    for day in range(DAYS, 0, -1):
        day_start = NOW - timedelta(days=day)
        # разброс объёма в пределах 3% — это нормальный шум, а не аномалия
        count = ROWS_PER_DAY + (day % 7) * 5 - 15
        for i in range(count):
            rows.append((
                1000 + (i % 250),
                round(50 + (i % 97) * 1.7, 2),
                "paid" if i % 10 else "refunded",
                day_start + timedelta(minutes=i % 1400),
            ))
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO orders (customer_id, amount, status, created_at)"
                " VALUES (%s, %s, %s, %s)", rows)
    print(f"загружено строк за {DAYS} дней: {len(rows)}")


def fill_today(rows_count: int, minutes_ago: int) -> None:
    """Текущий день. Два рычага: сколько строк и насколько свежая последняя."""
    last_ts = NOW - timedelta(minutes=minutes_ago)
    rows = [(
        1000 + (i % 250),
        round(50 + (i % 97) * 1.7, 2),
        "paid" if i % 10 else "refunded",
        last_ts - timedelta(minutes=i),
    ) for i in range(rows_count)]
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO orders (customer_id, amount, status, created_at)"
                " VALUES (%s, %s, %s, %s)", rows)
    print(f"текущий день: {rows_count} строк, последняя запись {minutes_ago} мин назад")


if __name__ == "__main__":
    recreate_database()
    create_schema()
    fill_history()
    fill_today(rows_count=498, minutes_ago=25)
    with psycopg.connect(DSN) as conn:
        total = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
        print("всего строк в orders:", total)
