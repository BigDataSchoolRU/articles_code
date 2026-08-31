# psycopg 3.3.4, PostgreSQL 18.4 (Homebrew), прогнано на стенде 2026-08-31
"""Классические операции над OLAP-кубом (slice, dice, drill-down/roll-up, pivot)
как обычный SQL поверх звёздной схемы — это и есть ROLAP: куб не хранится отдельной
структурой, а считается join'ом факта и измерений на каждый запрос.
"""
import psycopg

DB_NAME = "olap_demo"

BASE_JOIN = """
FROM fact_sales f
JOIN dim_date d ON d.date_id = f.date_id
JOIN dim_product p ON p.product_id = f.product_id
JOIN dim_store s ON s.store_id = f.store_id
"""

# SLICE: фиксируем одно измерение (год = 2025), смотрим срез куба по категориям
SLICE = f"""
SELECT p.category, sum(f.revenue) AS revenue
{BASE_JOIN}
WHERE d.year = 2025
GROUP BY p.category
ORDER BY revenue DESC;
"""

# DICE: фиксируем несколько измерений сразу (год, квартал, регион) — вырезаем
# из куба меньший подкуб, а не одну плоскость
DICE = f"""
SELECT p.category, s.store_name, sum(f.revenue) AS revenue
{BASE_JOIN}
WHERE d.year = 2025 AND d.quarter = 4 AND s.region = 'North'
GROUP BY p.category, s.store_name
ORDER BY revenue DESC
LIMIT 5;
"""

# ROLL-UP: ROLLUP(year, quarter) даёт иерархию итогов снизу вверх — по кварталу,
# по году и общий итог одним запросом, каждая строка помечена GROUPING()
ROLLUP = f"""
SELECT
    d.year,
    d.quarter,
    sum(f.revenue) AS revenue,
    grouping(d.year, d.quarter) AS grouping_level
{BASE_JOIN}
GROUP BY ROLLUP (d.year, d.quarter)
ORDER BY d.year NULLS LAST, d.quarter NULLS LAST;
"""

# CUBE: CUBE(category, region) считает все сочетания измерений разом, включая
# частичные и общий итог — drill-down в любую комбинацию без повторного запроса
CUBE = f"""
SELECT
    p.category,
    s.region,
    sum(f.revenue) AS revenue,
    grouping(p.category, s.region) AS grouping_level
{BASE_JOIN}
GROUP BY CUBE (p.category, s.region)
ORDER BY grouping_level, p.category NULLS LAST, s.region NULLS LAST;
"""

# PIVOT: сводная таблица категория x квартал через FILTER — тот же принцип,
# что и электронная сводная таблица поверх куба
PIVOT = f"""
SELECT
    p.category,
    sum(f.revenue) FILTER (WHERE d.quarter = 1) AS q1,
    sum(f.revenue) FILTER (WHERE d.quarter = 2) AS q2,
    sum(f.revenue) FILTER (WHERE d.quarter = 3) AS q3,
    sum(f.revenue) FILTER (WHERE d.quarter = 4) AS q4
{BASE_JOIN}
WHERE d.year = 2025
GROUP BY p.category
ORDER BY p.category;
"""


def show(conn: psycopg.Connection, title: str, sql: str) -> None:
    print(f"\n--- {title} ---")
    cur = conn.execute(sql)
    cols = [c.name for c in cur.description]
    print(" | ".join(cols))
    for row in cur.fetchall():
        print(" | ".join(str(v) for v in row))


def main() -> None:
    with psycopg.connect(dbname=DB_NAME) as conn:
        show(conn, "SLICE: выручка по категориям, 2025 год", SLICE)
        show(conn, "DICE: категория x магазин, 2025 Q4, регион North", DICE)
        show(conn, "ROLL-UP: год -> квартал -> общий итог", ROLLUP)
        show(conn, "CUBE: категория x регион, все сочетания", CUBE)
        show(conn, "PIVOT: категория x квартал, 2025 год", PIVOT)


if __name__ == "__main__":
    main()
