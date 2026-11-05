# psycopg 3.3.8, PostgreSQL 18.6, Python 3.12.3, прогнано на стенде 2026-11-05
"""Минимальный движок Reverse ETL: модель -> diff со снимком прошлого прогона -> батчи в API CRM.

Запуск: python sync.py --sync contacts_mirror --mode mirror
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request

import psycopg

DSN = os.environ.get("DWH_DSN", "postgresql://demo:demo@127.0.0.1:55433/dwh")
CRM_URL = os.environ.get("CRM_URL", "http://127.0.0.1:18080")

# Модель: обычный SQL-запрос к хранилищу. Обязателен уникальный ключ pk,
# по нему строки сопоставляются между прогонами и с записями в CRM.
MODEL_SQL = """
SELECT customer_id::text AS pk, email, plan, ltv, churn_risk
FROM analytics.customer_scores
"""

# Маппинг полей: колонка модели -> поле объекта в CRM
FIELD_MAP = {"email": "email", "plan": "plan_tier", "ltv": "lifetime_value",
             "churn_risk": "churn_risk"}

# Diff результатов запроса со снимком: FULL OUTER JOIN по первичному ключу.
# Хэш считается по значениям полей, поэтому UPDATE без смены значений изменением не считается.
DIFF_SQL = f"""
WITH model AS (
    SELECT m.pk, md5((to_jsonb(m) - 'pk')::text) AS row_hash, to_jsonb(m) - 'pk' AS payload
    FROM ({MODEL_SQL}) AS m
),
snap AS (
    SELECT pk, row_hash FROM reverse_etl.sync_snapshot WHERE sync_name = %(sync)s
)
SELECT CASE
           WHEN snap.pk IS NULL THEN 'added'
           WHEN model.pk IS NULL THEN 'removed'
           WHEN model.row_hash <> snap.row_hash THEN 'changed'
           ELSE 'unchanged'
       END AS op,
       coalesce(model.pk, snap.pk) AS pk, model.row_hash, model.payload
FROM model FULL OUTER JOIN snap ON snap.pk = model.pk
ORDER BY length(coalesce(model.pk, snap.pk)), coalesce(model.pk, snap.pk)
"""

stats = {"requests": 0, "throttled": 0}


def post(path, body, max_retries=5):
    """POST в CRM с повтором по 429 и паузой из заголовка Retry-After."""
    data = json.dumps(body).encode()
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(f"{CRM_URL}{path}", data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        stats["requests"] += 1
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, attempt
        except urllib.error.HTTPError as err:
            if err.code != 429 or attempt == max_retries:
                raise
            stats["throttled"] += 1
            wait = int(err.headers.get("Retry-After", "1"))
            print(f"    429 Too Many Requests, Retry-After={wait} с, ждём", flush=True)
            time.sleep(wait)


def to_crm(pk, payload):
    record = {"external_id": pk}
    record.update({FIELD_MAP[col]: val for col, val in payload.items()})
    return record


def batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", required=True, help="имя синхронизации и объекта в CRM")
    ap.add_argument("--mode", choices=["upsert", "mirror"], default="upsert")
    ap.add_argument("--batch-size", type=int, default=5)
    args = ap.parse_args()
    started = time.monotonic()
    stats.update(requests=0, throttled=0)

    with psycopg.connect(DSN) as conn:
        rows = conn.execute(DIFF_SQL, {"sync": args.sync}).fetchall()
        conn.commit()
        diff = {"added": [], "changed": [], "removed": [], "unchanged": []}
        for op, pk, row_hash, payload in rows:
            diff[op].append((pk, row_hash, payload))
        print(f"[{args.sync}, mode={args.mode}] "
              + " ".join(f"{op}={len(v)}" for op, v in diff.items()))
        for op in ("added", "changed", "removed"):
            if diff[op]:
                print(f"  {op}: pk " + ", ".join(pk for pk, _, _ in diff[op]))

        # added и changed уходят одним потоком upsert: CRM сам решит, создать или обновить
        to_send = diff["added"] + diff["changed"]
        total = (len(to_send) + args.batch_size - 1) // args.batch_size
        for n, batch in enumerate(batches(to_send, args.batch_size), 1):
            status, retries = post(f"/objects/{args.sync}/upsert",
                                   {"records": [to_crm(pk, p) for pk, _, p in batch]})
            print(f"  batch {n}/{total} upsert {len(batch)} записей -> {status}"
                  + (f" после {retries} повтора" if retries else ""), flush=True)
            # снимок двигается только за подтверждённым батчем: при падении
            # следующий прогон переотправит лишь то, что не дошло
            with conn.transaction():
                conn.cursor().executemany(
                    """INSERT INTO reverse_etl.sync_snapshot (sync_name, pk, row_hash)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (sync_name, pk)
                       DO UPDATE SET row_hash = EXCLUDED.row_hash, synced_at = now()""",
                    [(args.sync, pk, h) for pk, h, _ in batch])

        removed = [pk for pk, _, _ in diff["removed"]]
        if removed and args.mode == "mirror":
            status, _ = post(f"/objects/{args.sync}/delete", {"external_ids": removed})
            print(f"  delete {len(removed)} записей -> {status}")
        elif removed:
            print(f"  removed={len(removed)}: режим upsert удаления не отправляет, "
                  "записи остаются в CRM")
        if removed:
            with conn.transaction():
                conn.execute("DELETE FROM reverse_etl.sync_snapshot "
                             "WHERE sync_name = %s AND pk = ANY(%s)", (args.sync, removed))

    print(f"  итог: отправлено записей {len(to_send)}, HTTP-запросов {stats['requests']}, "
          f"из них 429: {stats['throttled']}, время {time.monotonic() - started:.1f} с")


if __name__ == "__main__":
    main()
