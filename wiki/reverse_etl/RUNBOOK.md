# RUNBOOK: Reverse ETL на PostgreSQL и имитации CRM

Пошаговый прогон демо к статье [Reverse ETL](https://bigdataschool.ru/wiki/reverse_etl/).
Хранилище играет PostgreSQL в Docker, приёмник играет `mock_crm.py`, движок синхронизации
это `sync.py` на сотню строк.

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6` |
| Python | 3.12 |
| psycopg | 3.3.8 (`psycopg[binary]`) |
| Docker | с плагином Compose |

Postgres слушает `127.0.0.1:55433`, пользователь, пароль и база `demo`/`demo`/`dwh`. Имитация
CRM слушает `127.0.0.1:18080`. Если порты заняты, поменяйте их и задайте переменные:

- `DWH_DSN=postgresql://demo:demo@127.0.0.1:<порт>/dwh` для `sync.py`;
- `CRM_PORT=<порт>` для `mock_crm.py` и `CRM_URL=http://127.0.0.1:<порт>` для `sync.py`.

Лимит CRM задаётся переменными `CRM_RATE_LIMIT` (запросов в окно, по умолчанию 2),
`CRM_WINDOW_S` (длина окна, 1 с) и `CRM_MAX_BATCH` (записей в запросе, 10).

## Шаг 1. Поднять хранилище

```bash
docker compose up -d --wait
docker compose exec -T dwh psql -U demo -d dwh -Atc "SELECT count(*) FROM analytics.customer_scores"
```

Ожидаемо: `25`. `init.sql` выполняется только при первом старте с пустым томом, поэтому для
чистого повтора гасите стенд с `-v`.

## Шаг 2. Окружение Python и имитация CRM

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python mock_crm.py &
curl -s http://127.0.0.1:18080/health
```

Ожидаемо: строка `mock CRM на http://127.0.0.1:18080, лимит 2 запросов/1.0 с, батч до 10 записей`
и ответ `{"status": "ok"}`.

## Шаг 3. Первая синхронизация

Две синхронизации одной модели в два объекта CRM, чтобы потом сравнить режимы:

```bash
.venv/bin/python sync.py --sync contacts_mirror --mode mirror
.venv/bin/python sync.py --sync contacts_upsert --mode upsert
```

Снимка ещё нет, поэтому все 25 строк идут как `added`, пятью батчами по 5 записей. Лимит
2 запроса в секунду срабатывает, `sync.py` ждёт `Retry-After` и повторяет батч:

```
[contacts_mirror, mode=mirror] added=25 changed=0 removed=0 unchanged=0
  batch 1/5 upsert 5 записей -> 200
  batch 2/5 upsert 5 записей -> 200
    429 Too Many Requests, Retry-After=1 с, ждём
  batch 3/5 upsert 5 записей -> 200 после 1 повтора
  ...
  итог: отправлено записей 25, HTTP-запросов 7, из них 429: 2, время 2.3 с
```

На каком батче придёт 429, зависит от того, куда попало начало секундного окна, поэтому номер
батча и число 429 между прогонами могут отличаться.

## Шаг 4. Изменить витрину

```bash
docker compose exec -T dwh psql -U demo -d dwh < changes.sql
```

Ожидаемо: `UPDATE 1` трижды, `INSERT 0 1`, `DELETE 1`. Третий UPDATE (`SET plan = plan` для
клиента 5) значений не меняет.

## Шаг 5. Вторая синхронизация: уходит только разница

```bash
.venv/bin/python sync.py --sync contacts_mirror --mode mirror
.venv/bin/python sync.py --sync contacts_upsert --mode upsert
```

Ожидаемо в обоих:

```
added=1 changed=2 removed=1 unchanged=22
  added: pk 26
  changed: pk 7, 12
  removed: pk 3
```

Клиента 5 среди `changed` нет: хэш строки не изменился. В режиме `mirror` приходит
`delete 1 записей -> 200`, в режиме `upsert` строка
`removed=1: режим upsert удаления не отправляет, записи остаются в CRM`.

Проверить приёмник:

```bash
curl -s http://127.0.0.1:18080/objects/contacts_mirror | python3 -c "import json,sys; print(json.load(sys.stdin)['count'])"
curl -s http://127.0.0.1:18080/objects/contacts_upsert | python3 -c "import json,sys; print(json.load(sys.stdin)['count'])"
```

Ожидаемо: `25` и `26`. Ушедший клиент 3 остался в объекте `contacts_upsert`.

## Шаг 6. Третья синхронизация без изменений

```bash
.venv/bin/python sync.py --sync contacts_mirror --mode mirror
```

Ожидаемо: `added=0 changed=0 removed=0 unchanged=25` и `HTTP-запросов 0`.

## Шаг 7. Погасить стенд

```bash
kill %1
docker compose down -v
```

## Если не так

- **`the database system is shutting down` сразу после `up`.** Во время `initdb` контейнер
  поднимает временный сервер только на сокете и потом перезапускает его. Healthcheck в
  `docker-compose.yml` проверяет TCP (`pg_isready -h 127.0.0.1`), чтобы `--wait` дождался
  рабочего сервера. Если меняли healthcheck, верните `-h 127.0.0.1`.
- **Вторая синхронизация снова шлёт все 25 строк.** Снимок не записался: проверьте
  `SELECT sync_name, count(*) FROM reverse_etl.sync_snapshot GROUP BY 1`. Снимок хранится по
  имени синхронизации, поэтому опечатка в `--sync` даёт новую синхронизацию с пустым снимком.
- **`Address already in use` у `mock_crm.py`.** Прошлый процесс не погашен: `kill %1` в той же
  оболочке либо другой порт через `CRM_PORT` и `CRM_URL`.
- **`413` от CRM.** Батч больше `CRM_MAX_BATCH`: уменьшите `--batch-size`.
- **`urllib.error.HTTPError: HTTP Error 429` в трейсбеке.** Повторы кончились (`max_retries=5`):
  лимит слишком жёсткий для размера батча, увеличьте `CRM_RATE_LIMIT` или батч.
- **Хотите начать с нуля.** `docker compose down -v` стирает и витрину, и снимок; перезапуск
  `mock_crm.py` очищает приёмник.
