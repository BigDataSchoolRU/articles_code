# duckdb 1.5.5, прогнано на стенде 2026-09-05
"""Serving layer: отвечает на запрос объединением batch_view (полная история до watermark)
и speed_view (дельта после watermark). Показывает разницу между устаревшим ответом от одного
batch layer и полным ответом serving layer, плюс сверяет merge с честным пересчётом по всему
мастер-датасету, чтобы доказать, что объединение двух путей не потеряло и не задвоило данные."""
from pathlib import Path

import duckdb

DB_FILE = Path(__file__).parent / "lambda_view.duckdb"
MASTER_FILE = Path(__file__).parent / "master_dataset.jsonl"


def main() -> None:
    con = duckdb.connect(str(DB_FILE))
    watermark = con.execute("SELECT watermark FROM batch_meta").fetchone()[0]
    print(f"watermark batch_view: {watermark}")

    print()
    print("=== ответ только от batch layer (устаревший, события после watermark не видны) ===")
    batch_only = con.execute("SELECT page, views FROM batch_view ORDER BY page").fetchall()
    for page, views in batch_only:
        print(f"  {page}: {views}")

    print()
    print("=== ответ serving layer: batch_view + speed_view ===")
    merged = con.execute("""
        SELECT page, SUM(views) AS views FROM (
            SELECT page, views FROM batch_view
            UNION ALL
            SELECT page, views FROM speed_view
        )
        GROUP BY page ORDER BY page
    """).fetchall()
    for page, views in merged:
        print(f"  {page}: {views}")

    print()
    print("=== сверка: честный пересчёт по всему мастер-датасету ===")
    ground_truth = con.execute(f"""
        SELECT page, SUM(views) AS views
        FROM read_json_auto('{MASTER_FILE}')
        GROUP BY page ORDER BY page
    """).fetchall()
    for page, views in ground_truth:
        print(f"  {page}: {views}")

    merged_dict, truth_dict, batch_dict = dict(merged), dict(ground_truth), dict(batch_only)
    print()
    print(f"serving layer совпал с честным пересчётом: {merged_dict == truth_dict}")
    missed = sum(truth_dict[p] - batch_dict.get(p, 0) for p in truth_dict)
    print(f"просмотров недосчитал бы ответ только от batch layer: {missed}")

    con.close()


if __name__ == "__main__":
    main()
