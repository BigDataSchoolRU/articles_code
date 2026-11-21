# duckdb==2.0.0 | собственный код демо, проверен прогоном на DuckDB 2.0.0 LTS
"""Шаг 4. EXPLAIN ANALYZE: projection pushdown и filter pushdown при чтении Parquet.

Запрос A читает 2 столбца из 11 без фильтра: видно, сколько байт реально прочитано.
Запрос B фильтрует узкий диапазон дат: благодаря статистике row group
DuckDB пропускает почти все группы. Затем тот же запрос B гоняем
с выключенным оптимизатором filter_pushdown и сравниваем время.
"""
import time

import duckdb

PQ = "read_parquet('data/orders.parquet')"
QUERY_A = f"SELECT region, sum(price) AS s FROM {PQ} GROUP BY region"
QUERY_B = (
    f"SELECT count(*) AS n, sum(price * quantity) AS s FROM {PQ} "
    "WHERE order_date BETWEEN DATE '2024-03-01' AND DATE '2024-03-07'"
)
KEYS = ("Projections", "Filters", "Data Read", "Row Groups", "Rows Scanned", "Total Files Read")

con = duckdb.connect()
total_cols = len(con.sql(f"SELECT * FROM {PQ} LIMIT 0").columns)
print(f"Столбцов в файле: {total_cols}")


def explain(label: str, sql: str) -> None:
    # EXPLAIN ANALYZE исполняет запрос и возвращает план с фактическими метриками
    plan = con.sql("EXPLAIN ANALYZE " + sql).fetchall()[0][1]
    print(f"===== {label} =====")
    print(plan)
    print(f"--- ключевые строки плана {label}:")
    for line in plan.splitlines():
        if any(k in line for k in KEYS):
            print(line)


explain("Запрос A (2 столбца, без фильтра)", QUERY_A)
explain("Запрос B (фильтр по дате)", QUERY_B)


def best_of(sql: str, runs: int = 3) -> tuple[float, tuple]:
    best, res = float("inf"), None
    for _ in range(runs):
        t0 = time.perf_counter()
        # В DuckDB 2.0 у relation нет fetchone(): берём первую строку из fetchall()
        res = con.sql(sql).fetchall()[0]
        best = min(best, time.perf_counter() - t0)
    return best, res


t_on, r_on = best_of(QUERY_B)
print(f"Запрос B с оптимизатором по умолчанию: {t_on:.4f} с (лучший из 3)")

# Выключаем проталкивание фильтров: теперь сканер читает все row groups
con.execute("SET disabled_optimizers = 'filter_pushdown'")
t_off, r_off = best_of(QUERY_B)
print(f"Запрос B с disabled_optimizers='filter_pushdown': {t_off:.4f} с (лучший из 3)")
explain("Запрос B без filter_pushdown", QUERY_B)
con.execute("RESET disabled_optimizers")

same = r_on[0] == r_off[0] and abs(r_on[1] - r_off[1]) < 1e-6 * max(1.0, abs(r_on[1]))
print(f"Результаты совпали: {same}, строк в диапазоне: {r_on[0]}")
con.close()
if not same:
    raise SystemExit(1)
