# DuckDB 1.5.5, прогнано на стенде 2026-08-26 (Python 3.12.13, ~/work/wiki/.venv)
"""
Демо медальонной архитектуры на DuckDB: Bronze -> Silver -> Gold на примере заказов.

Показывает три вещи, которые в тексте статьи описаны словами:
1. Bronze хранит сырьё как есть, включая дубли и невалидные строки, без отказа в приёме.
2. Переход Bronze -> Silver идёт через MERGE INTO по естественному ключу, поэтому повторный
   прогон того же батча не плодит дублей (идемпотентность), а невалидные строки отсеиваются
   с протоколом причины.
3. Переход Silver -> Gold это полный пересчёт агрегата (CREATE OR REPLACE), а не инкремент:
   Gold идемпотентен по построению, потому что каждый раз считается заново из Silver.
"""

import duckdb

DB_PATH = "medallion_demo.duckdb"


def reset_db(con):
    """Схема демо: одна витрина заказов на трёх слоях."""
    con.execute("DROP TABLE IF EXISTS bronze_orders")
    con.execute("DROP TABLE IF EXISTS silver_orders")
    con.execute("DROP TABLE IF EXISTS gold_daily_category_revenue")
    con.execute("""
        CREATE TABLE bronze_orders (
            order_id     VARCHAR,
            customer_id  VARCHAR,
            category     VARCHAR,
            amount_raw   VARCHAR,
            order_date   VARCHAR,
            batch_id     INTEGER,
            ingested_at  TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE silver_orders (
            order_id    VARCHAR PRIMARY KEY,
            customer_id VARCHAR,
            category    VARCHAR,
            amount      DECIMAL(10, 2),
            order_date  DATE
        )
    """)


def ingest_bronze(con, rows, batch_id):
    """Bronze не валидирует и не дедуплицирует — грузим строки как пришли из источника."""
    con.executemany(
        """
        INSERT INTO bronze_orders
            (order_id, customer_id, category, amount_raw, order_date, batch_id, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, now())
        """,
        [(*row, batch_id) for row in rows],
    )


def bronze_to_silver(con, batch_id):
    """
    Валидация и дедуп на входе в Silver, затем идемпотентный upsert по order_id.

    Дедуп берёт последнюю по времени загрузки строку на order_id внутри батча — так
    закрывается случай, когда источник в одном файле прислал две версии одного заказа.
    Строки без customer_id или с amount_raw, который не приводится к числу, в Silver не
    попадают вообще: они остаются в Bronze как есть, это и есть аудиторский след ошибки.
    """
    rejected = con.execute(
        """
        SELECT order_id, customer_id, amount_raw
        FROM bronze_orders
        WHERE batch_id = ?
          AND (customer_id IS NULL OR TRY_CAST(amount_raw AS DECIMAL(10, 2)) IS NULL)
        """,
        [batch_id],
    ).fetchall()

    con.execute(
        """
        MERGE INTO silver_orders AS s
        USING (
            SELECT order_id, customer_id, category,
                   CAST(amount_raw AS DECIMAL(10, 2)) AS amount,
                   CAST(order_date AS DATE) AS order_date
            FROM (
                SELECT *,
                       row_number() OVER (
                           PARTITION BY order_id ORDER BY ingested_at DESC
                       ) AS rn
                FROM bronze_orders
                WHERE batch_id = ?
                  AND customer_id IS NOT NULL
                  AND TRY_CAST(amount_raw AS DECIMAL(10, 2)) IS NOT NULL
            )
            WHERE rn = 1
        ) AS b
        ON s.order_id = b.order_id
        WHEN MATCHED THEN UPDATE SET
            customer_id = b.customer_id,
            category = b.category,
            amount = b.amount,
            order_date = b.order_date
        WHEN NOT MATCHED THEN INSERT (order_id, customer_id, category, amount, order_date)
            VALUES (b.order_id, b.customer_id, b.category, b.amount, b.order_date)
        """,
        [batch_id],
    )
    return rejected


def silver_to_gold(con):
    """Gold — полный пересчёт витрины, а не докатка дельты: так он идемпотентен сам по себе."""
    con.execute("""
        CREATE OR REPLACE TABLE gold_daily_category_revenue AS
        SELECT order_date, category,
               SUM(amount) AS revenue,
               COUNT(*) AS orders_count
        FROM silver_orders
        GROUP BY order_date, category
        ORDER BY order_date, category
    """)


def main():
    con = duckdb.connect(DB_PATH)
    reset_db(con)

    batch_1 = [
        ("ORD-1001", "CUST-1", "electronics", "129.90", "2026-08-20"),
        ("ORD-1002", "CUST-2", "books", "18.50", "2026-08-20"),
        ("ORD-1002", "CUST-2", "books", "18.50", "2026-08-20"),   # дубль строки в источнике
        ("ORD-1003", None, "electronics", "45.00", "2026-08-20"),  # нет customer_id
        ("ORD-1004", "CUST-3", "home", "not_a_number", "2026-08-20"),  # битая сумма
    ]

    print("=== батч 1: ингест в Bronze ===")
    ingest_bronze(con, batch_1, batch_id=1)
    print("Bronze строк:", con.execute("SELECT count(*) FROM bronze_orders").fetchone()[0])

    print("\n=== батч 1: первый прогон Bronze -> Silver ===")
    rejected = bronze_to_silver(con, batch_id=1)
    print("Отклонено строк:", len(rejected), rejected)
    silver_count_1 = con.execute("SELECT count(*) FROM silver_orders").fetchone()[0]
    print("Silver строк после первого прогона:", silver_count_1)

    print("\n=== батч 1: повторный прогон той же трансформации (идемпотентность) ===")
    bronze_to_silver(con, batch_id=1)
    silver_count_2 = con.execute("SELECT count(*) FROM silver_orders").fetchone()[0]
    print("Silver строк после повторного прогона:", silver_count_2)
    assert silver_count_1 == silver_count_2, "повторный прогон не должен плодить дубли"

    print("\n=== батч 2: исправление цены + новый заказ ===")
    batch_2 = [
        ("ORD-1001", "CUST-1", "electronics", "119.90", "2026-08-21"),  # исправлена цена и дата
        ("ORD-1005", "CUST-4", "books", "9.99", "2026-08-21"),
    ]
    ingest_bronze(con, batch_2, batch_id=2)
    bronze_to_silver(con, batch_id=2)
    silver_count_3 = con.execute("SELECT count(*) FROM silver_orders").fetchone()[0]
    print("Silver строк после батча 2:", silver_count_3)
    print(
        "Цена ORD-1001 после апдейта:",
        con.execute(
            "SELECT amount, order_date FROM silver_orders WHERE order_id = 'ORD-1001'"
        ).fetchone(),
    )

    print("\n=== Silver -> Gold: полный пересчёт витрины ===")
    silver_to_gold(con)
    print(con.execute("SELECT * FROM gold_daily_category_revenue").fetchdf().to_string(index=False))

    print("\n=== Gold после повторного вызова без изменений в Silver (тоже идемпотентно) ===")
    silver_to_gold(con)
    gold_count = con.execute("SELECT count(*) FROM gold_daily_category_revenue").fetchone()[0]
    print("Строк в Gold:", gold_count)

    con.close()


if __name__ == "__main__":
    main()
