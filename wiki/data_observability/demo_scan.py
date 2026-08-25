# soda-core 3.5.6, PostgreSQL 18.4, psycopg 3.3.4, прогнано на стенде 2026-08-25
# Три последовательных скана одной витрины: нормальный день, день с провалом
# объёма и просроченной свежестью, день со сменой схемы.
# Каждый скан не только проверяет правила, но и складывает метрики в историю:
# без истории следующий файл (demo_baseline.py) считать было бы не по чему.

import psycopg
from datetime import datetime, timezone
from soda.scan import Scan

DSN = "postgresql:///observability_demo"


def collect_metrics() -> dict:
    """Снимаем сырые метаданные витрины. Это работа сборщика, а не проверок:
    значения складываются в историю независимо от того, прошли правила или нет."""
    with psycopg.connect(DSN) as conn:
        row_count = conn.execute(
            "SELECT count(*) FROM orders WHERE created_at >= current_date"
        ).fetchone()[0]
        last_ts = conn.execute("SELECT max(created_at) FROM orders").fetchone()[0]
        column_count = conn.execute(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'orders'"
        ).fetchone()[0]
        avg_amount = conn.execute(
            # приведение типа нарочно: после смены схемы amount становится text,
            # и без каста сборщик метрик падает вместе с витриной
            "SELECT avg(amount::numeric) FROM orders"
            " WHERE created_at >= current_date"
        ).fetchone()[0]
    staleness = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
    return {
        "row_count_today": float(row_count),
        "staleness_minutes": round(staleness, 1),
        "column_count": float(column_count),
        "avg_amount": float(avg_amount or 0),
    }


def save_metrics(metrics: dict) -> None:
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO metric_history (scan_ts, dataset, metric, value)"
                " VALUES (now(), 'orders', %s, %s)",
                list(metrics.items()))


def close_scan_connections(scan: Scan) -> None:
    """Soda Core оставляет подключение к источнику открытым и в состоянии
    idle in transaction. Пока оно висит, любой ALTER TABLE по этой таблице
    будет ждать снятия блокировки. Штатный close_all_connections тут не
    помогает: в версии 3.5.6 он обходит пустой словарь, реальные подключения
    лежат на объектах источников."""
    for data_source in scan._data_source_manager.data_sources.values():
        if data_source.connection:
            data_source.connection.close()


def run_scan(title: str) -> None:
    """Один прогон правил Soda Core плюс запись метрик в историю."""
    print(f"\n===== {title} =====")
    scan = Scan()
    scan.set_data_source_name("orders_demo")
    scan.add_configuration_yaml_file("configuration.yml")
    scan.add_sodacl_yaml_file("checks.yml")
    scan.set_scan_definition_name(title)
    exit_code = scan.execute()
    print(scan.get_logs_text())
    print("код возврата скана:", exit_code, "(0 это всё прошло, 2 это есть провалы)")

    close_scan_connections(scan)

    metrics = collect_metrics()
    save_metrics(metrics)
    print("метрики в историю:", metrics)


def break_volume_and_freshness() -> None:
    """Инцидент первый: источник долил меньше данных и отстал по времени.
    Оставляем 120 сегодняшних строк вместо пятисот и сдвигаем их на 5 часов назад."""
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("""
            DELETE FROM orders
            WHERE created_at >= current_date
              AND id NOT IN (
                  SELECT id FROM orders
                  WHERE created_at >= current_date
                  ORDER BY id LIMIT 120)
        """)
        conn.execute("""
            UPDATE orders SET created_at = created_at - interval '5 hours'
            WHERE created_at >= current_date
        """)


def break_schema() -> None:
    """Инцидент второй: апстрим переименовал колонку и сменил тип суммы.
    Свежесть при этом чиним, чтобы провал был виден именно по схеме."""
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("UPDATE orders SET created_at = now()"
                     " WHERE id = (SELECT max(id) FROM orders)")
        conn.execute("ALTER TABLE orders RENAME COLUMN amount TO order_amount")
        conn.execute("ALTER TABLE orders ADD COLUMN amount text")
        conn.execute("UPDATE orders SET amount = order_amount::text")


if __name__ == "__main__":
    run_scan("СКАН 1: нормальный день")

    break_volume_and_freshness()
    run_scan("СКАН 2: провал объёма и просроченная свежесть")

    break_schema()
    run_scan("СКАН 3: смена схемы в источнике")
