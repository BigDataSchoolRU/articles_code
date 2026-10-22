# trino 0.340.0, Trino 484, прогнано на стенде 2026-10-22
"""План и время одного join-запроса в Trino.

Запуск: python join_plan.py "подпись состояния"
Печатает узлы join с распределением и оценками строк, затем медиану трёх запусков.
"""
import re
import statistics
import sys

import trino

QUERY = """
SELECT n.name, count(*) AS lines, sum(l.extendedprice) AS revenue
FROM iceberg.tpch.lineitem l
JOIN iceberg.tpch.orders o   ON l.orderkey = o.orderkey
JOIN iceberg.tpch.customer c ON o.custkey = c.custkey
JOIN iceberg.tpch.nation n   ON c.nationkey = n.nationkey
WHERE o.orderdate >= DATE '1995-01-01' AND o.orderdate < DATE '1995-04-01'
GROUP BY n.name
ORDER BY revenue DESC
"""

label = sys.argv[1] if len(sys.argv) > 1 else "текущее состояние"
conn = trino.dbapi.connect(host="127.0.0.1", port=8080, user="demo")
cur = conn.cursor()

# EXPLAIN показывает, что решил оптимизатор: порядок, тип распределения, оценки
cur.execute("EXPLAIN (TYPE DISTRIBUTED) " + QUERY)
plan = cur.fetchall()[0][0].splitlines()
print(f"--- план: {label}")
for i, line in enumerate(plan):
    if re.search(r"(Inner|Left|Right|Cross)Join\[|ScanFilter|TableScan\[", line):
        print(line.rstrip()[:160])
        est = next((p for p in plan[i + 1:i + 4] if "Estimates:" in p), None)
        if est:
            print(re.sub(r", cpu:.*", "}", est.rstrip()))

# Время: три запуска, берём медиану по серверному elapsed
times, peak = [], []
for _ in range(3):
    cur.execute(QUERY)
    rows = cur.fetchall()
    times.append(cur.stats["elapsedTimeMillis"])
    peak.append(cur.stats["peakMemoryBytes"])
print(f"--- время: {label}")
print(f"строк результата {len(rows)}, первая {rows[0][0]} {rows[0][1]}")
print(f"elapsed мс: {times}, медиана {statistics.median(times):.0f}")
print(f"peak memory МБ: {max(peak) / 2**20:.0f}")
