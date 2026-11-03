# postgres 18.6 + psycopg 3.3.7, прогнано на стенде 2026-11-03; коды ответов по draft-ietf-httpapi-idempotency-key-header-08
"""Хранилище ключей идемпотентности для обработчика POST /payments.

Клиент шлёт ключ в заголовке Idempotency-Key. Сервер запоминает ключ, отпечаток
тела запроса и готовый ответ. Повтор с тем же ключом получает сохранённый ответ,
а платёж второй раз не создаётся.
"""
import hashlib
import json
import os
import threading
import time
import uuid

import psycopg
from psycopg.types.json import Jsonb

DSN = os.environ.get("PG_DSN", "postgresql://demo:demo@127.0.0.1:55432/idem")
WORK_SECONDS = 1.0  # сколько «идёт» списание у платёжного шлюза


def setup():
    with psycopg.connect(DSN) as conn:
        conn.execute("DROP TABLE IF EXISTS payments, idempotency_keys")
        conn.execute(
            """CREATE TABLE payments (
                   id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                   account text, amount numeric(12,2))"""
        )
        conn.execute(
            """CREATE TABLE idempotency_keys (
                   key         text PRIMARY KEY,   -- арбитр: второй такой же ключ не вставится
                   fingerprint text NOT NULL,      -- sha256 тела запроса
                   status      text NOT NULL,      -- processing | done
                   response    jsonb,
                   created_at  timestamptz NOT NULL DEFAULT now())"""
        )


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def create_payment(conn, payload):
    """Сама неидемпотентная операция: каждый вызов даёт новую строку."""
    time.sleep(WORK_SECONDS)
    row = conn.execute(
        "INSERT INTO payments (account, amount) VALUES (%s, %s) RETURNING id",
        (payload["account"], payload["amount"]),
    ).fetchone()
    return {"payment_id": row[0], "status": "charged"}


def handle(key, payload):
    """Обработчик POST /payments. Возвращает (код HTTP, тело ответа)."""
    if key is None:
        return 400, {"error": "Idempotency-Key обязателен"}
    fp = fingerprint(payload)
    with psycopg.connect(DSN, autocommit=True) as conn:
        # шаг 1: занять ключ. Отдельный коммит, чтобы параллельный запрос сразу его увидел
        claimed = conn.execute(
            """INSERT INTO idempotency_keys (key, fingerprint, status)
               VALUES (%s, %s, 'processing')
               ON CONFLICT (key) DO NOTHING RETURNING key""",
            (key, fp),
        ).fetchone()

        if claimed is None:
            # ключ уже есть: решаем по сохранённой записи
            saved_fp, status, response = conn.execute(
                "SELECT fingerprint, status, response FROM idempotency_keys WHERE key = %s",
                (key,),
            ).fetchone()
            if saved_fp != fp:
                return 422, {"error": "ключ уже использован с другим телом запроса"}
            if status == "processing":
                return 409, {"error": "запрос с этим ключом ещё обрабатывается"}
            return 200, response  # повтор: отдаём тот же ответ, ничего не делаем

        # шаг 2: ключ наш, выполняем операцию и сохраняем ответ одной транзакцией
        with conn.transaction():
            response = create_payment(conn, payload)
            conn.execute(
                "UPDATE idempotency_keys SET status = 'done', response = %s WHERE key = %s",
                (Jsonb(response), key),
            )
        return 201, response


def handle_without_keys(payload):
    """Тот же обработчик без хранилища ключей, для сравнения."""
    with psycopg.connect(DSN, autocommit=True) as conn:
        return 201, create_payment(conn, payload)


def count_payments():
    with psycopg.connect(DSN) as conn:
        return conn.execute("SELECT count(*), coalesce(sum(amount), 0) FROM payments").fetchone()


def show(label, result):
    code, body = result
    print(f"{label:<46} -> {code} {json.dumps(body, ensure_ascii=False)}")


def main():
    setup()
    payload = {"account": "ACC-42", "amount": 1500}

    print("--- без ключа идемпотентности: клиент не дождался ответа и повторил ---")
    show("POST #1", handle_without_keys(payload))
    show("POST #2 (ретрай)", handle_without_keys(payload))
    print("платежей, сумма:", count_payments())

    setup()
    key = str(uuid.uuid4())  # клиент генерирует ключ один раз на операцию
    print(f"\n--- с ключом {key[:8]}...: тот же сценарий плюс гонка ---")

    # первый запрос и его ретрай уходят почти одновременно
    results = {}
    t1 = threading.Thread(target=lambda: results.__setitem__("first", handle(key, payload)))
    t1.start()
    time.sleep(0.2)
    show("POST #2 пока #1 ещё в работе", handle(key, payload))
    t1.join()
    show("POST #1", results["first"])
    show("POST #3 после завершения", handle(key, payload))
    show("POST #4 тот же ключ, amount=9999", handle(key, {**payload, "amount": 9999}))
    show("POST #5 без заголовка", handle(None, payload))
    print("платежей, сумма:", count_payments())


if __name__ == "__main__":
    main()
