# duckdb 2.0.0, прогнано на стенде 2026-11-03
"""Сверка двух материализаций одной витрины: table против incremental.

Печатает выручку по дням из обеих таблиц и дни, где они расходятся.
"""
from pathlib import Path

import duckdb

DB = Path(__file__).resolve().parent / "warehouse.duckdb"
con = duckdb.connect(str(DB), read_only=True)

rows = con.execute("""
    with t as (select sale_date, sum(revenue) as rev from marts.fct_sales_daily group by 1),
         i as (select sale_date, sum(revenue) as rev from marts.fct_sales_daily_incr group by 1)
    select coalesce(t.sale_date, i.sale_date) as day, t.rev as table_rev, i.rev as incr_rev
    from t full join i on t.sale_date = i.sale_date
    order by 1
""").fetchall()

print(f"{'день':<12}{'table':>12}{'incremental':>14}")
diff = 0
for day, t_rev, i_rev in rows:
    mark = "" if t_rev == i_rev else "   <-- расхождение"
    diff += mark != ""
    print(f"{day!s:<12}{t_rev!s:>12}{i_rev!s:>14}{mark}")

# Запрос аналитика к витрине: так её читает BI
print("\nвыручка по регионам (из витрины):")
for region, rev in con.execute(
        "select region, sum(revenue) from marts.fct_sales_daily group by 1 order by 2 desc").fetchall():
    print(f"  {region:<16}{rev}")

print(f"\nдней с расхождением: {diff}")
con.close()
