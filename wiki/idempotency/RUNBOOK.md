# RUNBOOK: идемпотентность на PostgreSQL

Пошаговый прогон демо к статье [Идемпотентность](https://bigdataschool.ru/wiki/idempotency/).

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6` |
| Python | 3.12 |
| psycopg | 3.3.7 (`psycopg[binary]`) |
| Docker | с плагином Compose |

Postgres слушает `127.0.0.1:55432`, пользователь, пароль и база `demo`/`demo`/`idem`. Если порт
занят, поменяйте его в `docker-compose.yml` и задайте переменную
`PG_DSN=postgresql://demo:demo@127.0.0.1:<порт>/idem`.

## Шаг 1. Поднять Postgres

```bash
docker compose up -d --wait
docker exec idempotency-postgres postgres --version
```

Ожидаемо: `postgres (PostgreSQL) 18.6 ...`. Флаг `--wait` возвращает управление, когда
healthcheck перешёл в `healthy`.

## Шаг 2. Окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install "psycopg[binary]==3.3.7"
```

## Шаг 3. Повторная загрузка партиции

```bash
.venv/bin/python partition_reload.py
```

Скрипт трижды грузит пять заказов за 2026-11-01: первая попытка падает после третьей строки,
вторая это ретрай, третья ручной перезапуск. Ожидаемые строки:

```
--- sales_naive ---
попытка 1: упали после 3 строк  строк=3 уникальных order_id=3 сумма=2540.50
попытка 2: успех                строк=8 уникальных order_id=5 сумма=9256.25
попытка 3: успех                строк=13 уникальных order_id=5 сумма=15972.00

--- sales_overwrite ---
попытка 1: упали после 3 строк  строк=0 уникальных order_id=0 сумма=0
попытка 2: успех                строк=5 уникальных order_id=5 сумма=6715.75
попытка 3: успех                строк=5 уникальных order_id=5 сумма=6715.75

--- sales_upsert ---
попытка 1 (WHERE IS DISTINCT FROM): затронуто строк=5  ...
попытка 2 (WHERE IS DISTINCT FROM): затронуто строк=0  ...
попытка 3 (без WHERE): затронуто строк=5  ...

--- дубль ключа внутри одной пачки ---
CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time
```

Шаг прошёл, если в `sales_overwrite` и `sales_upsert` после каждой успешной попытки ровно 5 строк
и сумма 6715.75, а в `sales_naive` строки копятся. Скрипт сам пересоздаёт таблицы, его можно
запускать сколько угодно раз.

## Шаг 4. Ключи идемпотентности для POST

```bash
.venv/bin/python idempotency_key_store.py
```

Ожидаемо: без ключа два платежа на 3000.00, с ключом один платёж на 1500.00 и коды ответов
409, 201, 200, 422, 400 в таком порядке. UUID ключа у вас будет свой.

```
POST #2 пока #1 ещё в работе                   -> 409 ...
POST #1                                        -> 201 {"payment_id": 1, "status": "charged"}
POST #3 после завершения                       -> 200 {"status": "charged", "payment_id": 1}
POST #4 тот же ключ, amount=9999               -> 422 ...
POST #5 без заголовка                          -> 400 ...
платежей, сумма: (1, Decimal('1500.00'))
```

## Шаг 5. Убрать стенд

```bash
docker compose down -v
```

## Если не так

- **`connection refused` на 55432.** Контейнер не поднялся или порт занят: `docker compose ps`,
  `docker compose logs postgres`.
- **409 не появился, а сразу 201 и 200.** Второй запрос ушёл уже после завершения первого.
  Увеличьте `WORK_SECONDS` в `idempotency_key_store.py`.
- **Порядок ключей в ответе 200 отличается от 201.** Это не ошибка: ответ хранится в `jsonb`, а
  `jsonb` не сохраняет порядок ключей. Если клиенту нужен побайтно тот же ответ, храните его в
  `text`.
