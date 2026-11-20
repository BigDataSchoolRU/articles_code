# duckdb==2.0.0 | демо bigdataschool.ru к статье «DuckDB для локальной аналитики», код написан по брифу, вывод фиксирует прогон selfcheck.py
"""Шаг 4. EXPLAIN ANALYZE по Parquet: projection pushdown, filter pushdown и пропуск групп строк по статистике."""
import sys
import time
import traceback
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import PARQUET, ensure_data, q  # noqa: E402

KEYWORDS = ("scan", "parquet", "projection", "filter", "rows", "total time")


def plan_text(con, prefix: str, sql: str) -> str:
    rows = con.execute(prefix + " " + sql).fetchall()
    return "\n".join(str(r[-1]) for r in rows)


def explain(con, sql: str):
    """EXPLAIN ANALYZE; при ошибке пробуем legacy-парсер, затем обычный EXPLAIN. Возвращает (как получен, текст)."""
    try:
        return "EXPLAIN ANALYZE", plan_text(con, "EXPLAIN ANALYZE", sql)
    except duckdb.Error as exc:
        print(f"EXPLAIN ANALYZE не прошёл: {type(exc).__name__}: {exc}")
    try:
        con.execute("SET enable_legacy_parser = true")
        try:
            return "EXPLAIN ANALYZE (legacy parser)", plan_text(con, "EXPLAIN ANALYZE", sql)
        finally:
            con.execute("SET enable_legacy_parser = false")
    except duckdb.Error as exc:
        print(f"EXPLAIN ANALYZE с legacy-парсером не прошёл: {type(exc).__name__}: {exc}")
    try:
        return "EXPLAIN", plan_text(con, "EXPLAIN", sql)
    except duckdb.Error as exc:
        print(f"EXPLAIN не прошёл: {type(exc).__name__}: {exc}")
    return "нет", ""


def highlights(plan: str) -> list:
    """Строки плана со сканом, проекциями, фильтрами и числом строк."""
    return [line for line in plan.splitlines() if any(k in line.lower() for k in KEYWORDS)]


def best_time(con, sql: str, runs: int = 3) -> float:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        times.append(time.perf_counter() - t0)
    return min(times)


def show_plan(title: str, kind: str, plan: str) -> None:
    print(f"\n===== {title}, получен через {kind} =====")
    print(plan)
    print("--- ключевые строки плана:")
    for line in highlights(plan):
        print(line)


def main() -> int:
    ensure_data()
    con = duckdb.connect()
    src = f"read_parquet('{q(PARQUET)}')"
    meta = f"parquet_metadata('{q(PARQUET)}')"

    # Что лежит в файле: число столбцов и групп строк
    try:
        columns = con.sql(f"DESCRIBE SELECT * FROM {src}").fetchall()
        print(f"Столбцов в файле: {len(columns)} ({', '.join(c[0] for c in columns)})")
    except duckdb.Error as exc:
        print(f"DESCRIBE не прошёл: {type(exc).__name__}: {exc}")
    try:
        # Уникальные группы считаем в Python, чтобы не зависеть от разбора агрегатов в метаданных
        rg_ids = {r[0] for r in con.execute(f"SELECT row_group_id FROM {meta}").fetchall()}
        print(f"Групп строк (row groups): {len(rg_ids)}")
    except duckdb.Error as exc:
        print(f"parquet_metadata не прочитан: {type(exc).__name__}: {exc}")
    try:
        stats = con.execute(
            f"SELECT row_group_id, stats_min, stats_max FROM {meta} "
            "WHERE path_in_schema = 'order_id' ORDER BY row_group_id LIMIT 3"
        ).fetchall()
        print("min/max order_id в первых группах строк:", stats)
    except duckdb.Error as exc:
        print(f"Статистику групп строк прочитать не удалось: {type(exc).__name__}: {exc}")

    # Запрос A: нужны 4 столбца из 8, фильтр по region и ts уходит в скан
    q_proj = (
        f"SELECT category, count(*) AS n, round(sum(amount), 2) AS total FROM {src} "
        "WHERE region = 'north' AND ts >= TIMESTAMP '2026-09-01' "
        "GROUP BY category ORDER BY total DESC LIMIT 5"
    )
    kind_a, plan_a = explain(con, q_proj)
    show_plan("Запрос A (projection + filter pushdown)", kind_a, plan_a)
    print("Запросу A нужны столбцы: category, amount, region, ts")

    # Запрос B: узкий диапазон order_id, лишние группы строк отсекаются по min/max
    q_range = (
        f"SELECT count(*) AS n, round(sum(amount), 2) AS total FROM {src} "
        "WHERE order_id BETWEEN 1000000 AND 1099999"
    )
    kind_b, plan_b = explain(con, q_range)
    show_plan("Запрос B (диапазон по order_id)", kind_b, plan_b)

    try:
        t_on = best_time(con, q_range)
        print(f"\nЗапрос B с оптимизатором по умолчанию: {t_on:.4f} с (лучший из 3)")
    except duckdb.Error as exc:
        print(f"Запрос B не выполнился: {type(exc).__name__}: {exc}")

    # Граничный случай: выключаем filter_pushdown и смотрим, что меняется в плане и времени
    try:
        con.execute("SET disabled_optimizers = 'filter_pushdown'")
        t_off = best_time(con, q_range)
        print(f"Запрос B с disabled_optimizers='filter_pushdown': {t_off:.4f} с (лучший из 3)")
        kind_off, plan_off = explain(con, q_range)
        print(f"--- ключевые строки плана B без filter_pushdown ({kind_off}):")
        for line in highlights(plan_off):
            print(line)
    except duckdb.Error as exc:
        print(f"Отключить filter_pushdown не удалось: {type(exc).__name__}: {exc}")
    finally:
        try:
            con.execute("SET disabled_optimizers = ''")
        except duckdb.Error:
            pass

    con.close()
    # Шаг считается пройденным, если план хотя бы одного вида получен для обоих запросов
    return 0 if plan_a and plan_b else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
