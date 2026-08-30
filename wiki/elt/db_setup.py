# PostgreSQL 18.4, psycopg 3.3.4, прогнано на стенде 2026-08-29
"""Готовит источник под ELT-конвейер: создаёт базу elt_demo и в ней таблицу
source.orders — имитацию OLTP-источника со схемой source, из которой в
реальном ELT данные забирает Airbyte/Fivetran/Meltano. Таблица сырая, "как
из источника", с типичными для реальной выгрузки дефектами: дублями строк,
пропусками в количестве и цене, разнобоем в написании региона. Эти дефекты
не разбираются здесь — ими займётся SQL-трансформация внутри хранилища
в elt_pipeline.py, а не этот скрипт.

Скрипт идемпотентный: таблица каждый раз пересоздаётся.
"""

import psycopg

# Локальный Homebrew-PostgreSQL, доверительная аутентификация по сокету.
ADMIN_DSN = "host=localhost port=5432 dbname=postgres user=techfriends"
DEMO_DSN = "host=localhost port=5432 dbname=elt_demo user=techfriends"

DDL = """
CREATE SCHEMA IF NOT EXISTS source;
DROP TABLE IF EXISTS source.orders;
CREATE TABLE source.orders (
    id          bigint,
    quantity    integer,
    unit_price  numeric(10,2),
    region      text,
    order_date  date,
    status      text
);
"""

# 5000 "чистых" строк источника — база, к которой затем добавляется грязь.
INSERT_BASE = """
INSERT INTO source.orders (id, quantity, unit_price, region, order_date, status)
SELECT g,
       (random() * 5 + 1)::int,
       round((random() * 400 + 20)::numeric, 2),
       (ARRAY['North', 'South', 'East', 'West'])[(random() * 3)::int + 1],
       date '2026-01-01' + (random() * 240)::int,
       (ARRAY['completed', 'completed', 'completed', 'cancelled', 'refunded'])[(random() * 4)::int + 1]
FROM generate_series(1, 5000) AS g;
"""

# Дубли: те же id повторно, как при повторной выгрузке источника без offset.
INSERT_DUPLICATES = """
INSERT INTO source.orders
SELECT * FROM source.orders WHERE id BETWEEN 1 AND 30;
"""

# Пропуски: часть заказов без количества или без цены — источник отдал NULL.
UPDATE_NULLS = """
UPDATE source.orders SET quantity = NULL WHERE id BETWEEN 100 AND 130;
UPDATE source.orders SET unit_price = NULL WHERE id BETWEEN 200 AND 220;
"""

# Разнобой в region: пробелы и регистр, типичный артефакт ручного ввода в источнике.
UPDATE_MESSY_REGION = """
UPDATE source.orders SET region = '  north  ' WHERE id BETWEEN 300 AND 320;
UPDATE source.orders SET region = 'SOUTH' WHERE id BETWEEN 400 AND 420;
"""


def ensure_database() -> None:
    """Создаёт базу elt_demo, если её ещё нет. CREATE DATABASE не идёт внутри
    транзакции, поэтому подключение переводится в autocommit."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'elt_demo'"
        ).fetchone()
        if exists:
            print("база elt_demo уже есть")
        else:
            conn.execute("CREATE DATABASE elt_demo")
            print("база elt_demo создана")


def rebuild_source() -> None:
    """Пересоздаёт source.orders и наполняет её чистыми строками плюс дефектами."""
    with psycopg.connect(DEMO_DSN, autocommit=True) as conn:
        conn.execute(DDL)
        conn.execute(INSERT_BASE)
        conn.execute(INSERT_DUPLICATES)
        conn.execute(UPDATE_NULLS)
        conn.execute(UPDATE_MESSY_REGION)
        total = conn.execute("SELECT count(*) FROM source.orders").fetchone()[0]
        dupes = conn.execute(
            "SELECT count(*) FROM (SELECT id FROM source.orders GROUP BY id HAVING count(*) > 1) d"
        ).fetchone()[0]
        nulls = conn.execute(
            "SELECT count(*) FROM source.orders WHERE quantity IS NULL OR unit_price IS NULL"
        ).fetchone()[0]
    print(f"таблица source.orders пересоздана, строк: {total}")
    print(f"  из них id с дублями: {dupes}, строк с NULL в quantity/unit_price: {nulls}")


if __name__ == "__main__":
    ensure_database()
    rebuild_source()
