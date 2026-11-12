# Saga pattern

Код к статье [Saga pattern](https://bigdataschool.ru/wiki/saga_pattern/).

Оркестрированная сага заказа интернет-магазина на PostgreSQL 18.6 и Python, без фреймворка, чтобы
механизм был виден целиком. Три сервиса (заказы, склад, оплата) живут в отдельных базах, общей
транзакции между ними нет. Оркестратор проводит заказ цепочкой локальных транзакций, после каждой
пишет шаг в журнал в своей базе, при отказе оплаты запускает компенсации в обратном порядке, после
рестарта дочитывает журнал и повторяет шаг с тем же ключом идемпотентности. Отдельные сценарии
показывают грязное чтение между сагами и semantic lock против него, а для сравнения двухфазный
коммит на `PREPARE TRANSACTION`, который держит блокировки после падения координатора.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | PostgreSQL 18.6 в Docker, порт `127.0.0.1:55440`, `max_prepared_transactions=10`, базы из `schema.sql` при первом старте |
| `requirements.txt` | `psycopg[binary]==3.3.8` |
| `schema.sql` | базы `orders`, `inventory`, `payments` с таблицами сервисов и база `saga` с журналом оркестратора |
| `services.py` | локальные транзакции и компенсации трёх сервисов, ключи идемпотентности, semantic lock на складе |
| `orchestrator.py` | шаги саги с типами compensable, pivot, retryable, журнал, повторы, компенсации, восстановление после падения |
| `saga_demo.py` | сценарии `all`, `happy`, `compensate`, `retry`, `crash`, `isolation`, `two_pc`, `two_pc_recover` |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, образ `postgres:18.6`, Python 3.10 или новее.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python saga_demo.py all
.venv/bin/python saga_demo.py two_pc
docker compose restart pg && docker compose up -d --wait
.venv/bin/python saga_demo.py two_pc_recover
docker compose down -v
```

Каждый сценарий начинает с чистых данных, порядок запуска не важен. `two_pc_recover` идёт
после `two_pc` и рестарта сервера.
