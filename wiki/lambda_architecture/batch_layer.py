# duckdb 1.5.5, прогнано на стенде 2026-09-05
"""Batch layer: полный пересчёт представления по всему мастер-датасету. Дорого по времени
(пересчитывается весь объём, а не только новые строки), зато точно — источник это неизменяемый
append-only лог, а не текущее состояние, которое можно было исправить задним числом."""
import time
from pathlib import Path

import duckdb

MASTER_FILE = Path(__file__).parent / "master_dataset.jsonl"
DB_FILE = Path(__file__).parent / "lambda_view.duckdb"


def main() -> None:
    if not MASTER_FILE.exists():
        raise SystemExit(f"нет мастер-датасета {MASTER_FILE}, сначала запустите event_producer.py")

    con = duckdb.connect(str(DB_FILE))
    t0 = time.time()
    # полный пересчёт: batch_view строится заново из всего файла, а не дописывается по хвосту
    con.execute(f"""
        CREATE OR REPLACE TABLE batch_view AS
        SELECT page, SUM(views) AS views, MAX(ts) AS last_ts
        FROM read_json_auto('{MASTER_FILE}')
        GROUP BY page
        ORDER BY page
    """)
    watermark, rows = con.execute(
        "SELECT MAX(ts), COUNT(*) FROM read_json_auto(?)", [str(MASTER_FILE)]
    ).fetchone()
    # watermark отмечает границу: всё с ts <= watermark уже учтено в batch_view,
    # speed layer работает только с тем, что строго новее
    con.execute("CREATE OR REPLACE TABLE batch_meta AS SELECT ? AS watermark", [watermark])
    elapsed = time.time() - t0

    print(f"пересчитано по {rows} событиям мастер-датасета за {elapsed:.3f} с")
    print(f"watermark (последний учтённый ts): {watermark}")
    print("batch_view:")
    for page, views, last_ts in con.execute("SELECT * FROM batch_view ORDER BY page").fetchall():
        print(f"  {page}: {views} просмотров (по ts <= {last_ts})")
    con.close()


if __name__ == "__main__":
    main()
