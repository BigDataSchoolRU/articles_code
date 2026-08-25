# PostgreSQL 18.4, psycopg 3.3.4, прогнано на стенде 2026-08-25
# Детекция аномалии по базовой линии. Здесь нет ни одного жёсткого порога:
# нормой считается то, что витрина сама показывала последние тридцать дней.

import psycopg
from statistics import median

DSN = "postgresql:///observability_demo"
Z_THRESHOLD = 3.5          # общепринятый порог для устойчивой z-оценки
MAD_TO_SIGMA = 0.6745      # перевод медианного отклонения в сигмы нормального закона

# Упрощённый граф происхождения: кто читает витрину заказов вниз по потоку.
# По нему считается не факт поломки, а её масштаб.
LINEAGE = {
    "orders": ["mart_daily_revenue", "dash_sales_overview",
               "ml_churn_features", "report_finance_monthly"],
    "mart_daily_revenue": ["dash_ceo_weekly"],
}


def daily_counts() -> list[tuple[str, int]]:
    """История дневных объёмов прямо из данных. В боевом решении её собирает
    сборщик метаданных, здесь достаточно группировки по дню."""
    with psycopg.connect(DSN) as conn:
        return conn.execute("""
            SELECT to_char(created_at::date, 'YYYY-MM-DD') AS day, count(*)
            FROM orders
            GROUP BY 1
            ORDER BY 1
        """).fetchall()


def robust_zscore(value: float, history: list[float]) -> float:
    """Устойчивая z-оценка на медиане и MAD. Обычные среднее и стандартное
    отклонение здесь не годятся: один выброс тянет базовую линию за собой
    и следующая такая же аномалия уже выглядит нормой."""
    base = median(history)
    mad = median([abs(x - base) for x in history])
    if mad == 0:
        return 0.0
    return (value - base) * MAD_TO_SIGMA / mad


def impact(dataset: str) -> list[str]:
    """Обход графа вниз по потоку: все потребители, до которых дойдёт проблема."""
    affected, queue = [], list(LINEAGE.get(dataset, []))
    while queue:
        node = queue.pop(0)
        if node not in affected:
            affected.append(node)
            queue.extend(LINEAGE.get(node, []))
    return affected


if __name__ == "__main__":
    rows = daily_counts()
    history = [float(c) for _, c in rows[:-1]]   # прошлые дни это база
    today_day, today_count = rows[-1]

    base = median(history)
    z = robust_zscore(float(today_count), history)

    print(f"дней в истории: {len(history)}")
    print(f"базовая линия (медиана дневного объёма): {base:.0f} строк")
    print(f"текущий день {today_day}: {today_count} строк")
    print(f"отклонение от базовой линии: {(today_count / base - 1) * 100:.1f}%")
    print(f"устойчивая z-оценка: {z:.1f} при пороге {Z_THRESHOLD}")

    # Тот же день глазами жёсткого правила из checks.yml
    print(f"\nправило row_count > 100 говорит: "
          f"{'провал' if today_count <= 100 else 'всё в порядке'}")

    if abs(z) > Z_THRESHOLD:
        consumers = impact("orders")
        print(f"детектор базовой линии говорит: АНОМАЛИЯ")
        print(f"затронуто потребителей вниз по потоку: {len(consumers)}")
        print("список:", ", ".join(consumers))
    else:
        print("детектор базовой линии говорит: в пределах нормы")
