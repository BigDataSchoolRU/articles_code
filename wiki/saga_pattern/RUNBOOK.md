# RUNBOOK: Saga pattern на PostgreSQL 18 и Python

Пошаговый прогон демо к статье [Saga pattern](https://bigdataschool.ru/wiki/saga_pattern/).
Один контейнер PostgreSQL 18.6, в нём четыре базы: `orders`, `inventory`, `payments` у трёх
сервисов интернет-магазина и `saga` с журналом оркестратора. Общей транзакции между базами нет,
поэтому заказ проходит как сага из пяти локальных транзакций:

| Шаг | Сервис | Тип | Компенсация |
|---|---|---|---|
| `create_order` | заказы | compensable | `cancel_order` |
| `reserve_stock` | склад | compensable | `release_stock` |
| `charge_payment` | оплата | pivot | нет, точка невозврата |
| `commit_reservation` | склад | retryable | не нужна |
| `confirm_order` | заказы | retryable | не нужна |

Оркестратор написан руками, без фреймворка, чтобы журнал, компенсации и повторы были видны
целиком. В продакшене эту роль берут Temporal, AWS Step Functions и похожие движки.

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6`, запущен с `max_prepared_transactions=10` |
| Python | 3.10 или новее, проверено на 3.12.3 |
| psycopg | 3.3.8, `psycopg[binary]` со встроенной libpq 18 |
| Docker | с плагином Compose |

Сервер слушает `127.0.0.1:55440`, пользователь и пароль `demo`/`demo`. Если порт занят, поменяйте
его в `docker-compose.yml` и задайте строку подключения в формате ключ=значение (имя базы код
добавит сам):

```bash
export SAGA_DSN="host=127.0.0.1 port=<порт> user=demo password=demo"
```

Сценарии саги идут по 0-2 секунды, `two_pc` около 4 секунд из-за `lock_timeout`. Полный
прогон вместе с подъёмом стенда и рестартом сервера на нашем стенде занял около 33 секунд. Миллисекунды в логе и случайные хвосты ключей в
контрольном прогоне у вас будут другими, статусы, остатки и балансы совпадут.

## Шаг 1. Поднять сервер и окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
docker compose exec -T pg psql -U demo -d demo -XAtc \
  "SELECT string_agg(datname, ', ' ORDER BY datname) FROM pg_database WHERE NOT datistemplate"
```

Ожидаемо: `Container saga-pattern-pg  Healthy` и список баз:

```
demo, inventory, orders, payments, postgres, saga
```

Каждый сценарий ниже сам очищает таблицы и кладёт исходные данные: на складе 10 чайников по 250,
на счёте `alice` 1000, на счёте `bob` 100.

## Шаг 2. Успешная сага

```bash
.venv/bin/python saga_demo.py happy
```

Оркестратор проходит пять шагов, после каждого пишет строку в журнал `saga_log`:

```
[S-happy] create_order       DO         DONE   заказ PENDING
[S-happy] reserve_stock      DO         DONE   резерв 2 шт., остаток 8
[S-happy] charge_payment     DO         DONE   списано 500, баланс 500.00
[S-happy] commit_reservation DO         DONE   резерв COMMITTED (строк 1)
[S-happy] confirm_order      DO         DONE   заказ APPROVED (строк 1)
[S-happy] сага -> COMPLETED
```

Шаг прошёл, если заказ `APPROVED`, остаток 8, резерв `COMMITTED`, у `alice` 500.

## Шаг 3. Отказ оплаты и компенсации

```bash
.venv/bin/python saga_demo.py compensate
```

У `bob` 100, заказ на 500. Оплата отклонена, и оркестратор запускает компенсации уже выполненных
шагов в обратном порядке:

```
[S-comp] charge_payment     DO         FAILED bob: недостаточно средств для 500
[S-comp] сага -> COMPENSATING
[S-comp] reserve_stock      COMPENSATE DONE   резерв снят, вернули 2 шт.
[S-comp] create_order       COMPENSATE DONE   заказ CANCELLED (строк 1)
[S-comp] сага -> COMPENSATED
```

Шаг прошёл, если остаток снова 10, резерв `RELEASED`, заказ `CANCELLED`, таблица платежей пуста.
Заказ и резерв не удалены, а получили новый статус: компенсация это новая транзакция, а не откат.

## Шаг 4. Сбой после точки невозврата

```bash
.venv/bin/python saga_demo.py retry
```

Деньги уже списаны, а `confirm_order` дважды отвечает таймаутом. После pivot сага не
компенсируется, а повторяет шаг, пока он не пройдёт:

```
[S-retry] confirm_order: попытка 1 не прошла (таймаут ответа сервиса), повтор
[S-retry] confirm_order: попытка 2 не прошла (таймаут ответа сервиса), повтор
[S-retry] confirm_order      DO         DONE   заказ APPROVED (строк 1)
[S-retry] сага -> COMPLETED
```

## Шаг 5. Падение оркестратора и идемпотентный повтор

```bash
.venv/bin/python saga_demo.py crash
```

Оркестратор запускается отдельным процессом и падает (`os._exit(1)`) сразу после того, как
`reserve_stock` закоммичен в базе склада, но до записи шага в журнал. Журнал знает только про
`create_order`, сага в состоянии `RUNNING`, а резерв на складе уже есть, остаток 8.

Рестарт оркестратора (`recover`) находит незавершённую сагу и повторяет `reserve_stock`.

Вариант 1, ключ шага `saga_id:step`. Повтор упирается в первичный ключ резерва и ничего не меняет:

```
[S-crash-idem] reserve_stock      DO         DONE   повтор: резерв с этим ключом уже есть, остаток не трогаем
...
kettle | 8
S-crash-idem:reserve_stock | 2   | COMMITTED
```

Вариант 2, контрольный: ключ генерируется заново на каждую попытку. Повтор резервирует товар
второй раз, заказ на 2 чайника держит 4:

```
[S-crash-naive] reserve_stock      DO         DONE   резерв 2 шт., остаток 6
...
S-crash-naive:reserve_stock:<хвост 1> | 2   | COMMITTED
S-crash-naive:reserve_stock:<хвост 2> | 2   | COMMITTED
```

## Шаг 6. Нет изоляции между сагами

```bash
.venv/bin/python saga_demo.py isolation
```

На складе один чайник. Сага A (`bob`, денег не хватит) резервирует его и останавливается перед
оплатой. В этот момент стартует сага B (`alice`, денег хватает).

Вариант 1: склад видит остаток 0 и отвечает «нет на складе». B отменяется, затем A не может
оплатить и тоже отменяется. Итог: чайник на складе, оба заказа `CANCELLED`. Сага B прочитала
промежуточное состояние саги A, которое потом откатилось.

```
[S-B-alice] reserve_stock      DO         FAILED kettle: нет на складе
...
kettle | 1
S-A-bob   | bob      | 1   | 250.00 | CANCELLED
S-B-alice | alice    | 1   | 250.00 | CANCELLED
```

Вариант 2, semantic lock: резерв в статусе `PENDING` означает «товар занят незавершённой сагой».
Склад отвечает временной ошибкой, B повторяет резерв, A тем временем компенсируется, и следующий
повтор B проходит:

```
[S-B-alice] reserve_stock: попытка 1 не прошла (kettle: товар в резерве у незавершённой саги (1)), повтор
[S-A-bob] charge_payment     DO         FAILED bob: недостаточно средств для 250
...
[S-B-alice] reserve_stock      DO         DONE   резерв 1 шт., остаток 0
[S-B-alice] сага -> COMPLETED
```

## Шаг 7. Для сравнения: двухфазный коммит

```bash
.venv/bin/python saga_demo.py two_pc
```

Координатор выполняет `PREPARE TRANSACTION` в базах `inventory` и `payments` и падает, не
отправив `COMMIT PREPARED`. Обе подготовленные транзакции видны в `pg_prepared_xacts` и держат
блокировки без процесса-владельца. Чтение строки проходит и видит старое значение, а запись в ту
же строку ждёт и падает по `lock_timeout`:

```
-- чтение не блокируется, но видит старое значение: 10
-- запись в ту же строку ждала 3.0 с и упала: LockNotAvailable: canceling statement due to lock timeout
```

Перезапустите сервер и выполните восстановление:

```bash
docker compose restart pg && docker compose up -d --wait
.venv/bin/python saga_demo.py two_pc_recover
```

Подготовленные транзакции пережили рестарт и по-прежнему блокируют запись. Только после
`COMMIT PREPARED` в обеих базах остаток становится 9, баланс `alice` 750, `pg_prepared_xacts` пуст.

## Шаг 8. Уборка

```bash
docker compose down -v
```

## Если не так

- **`ERROR: prepared transactions are disabled`** на шаге 7: сервер поднят без
  `max_prepared_transactions`. Проверьте `command` в `docker-compose.yml` и пересоздайте контейнер.
- **`FATAL: the database system is shutting down`** сразу после `up`: healthcheck без `-h 127.0.0.1`
  отвечает «готов» ещё во время `initdb`. Используйте healthcheck из этого `docker-compose.yml`.
- **Базы `orders`, `inventory`, `payments` не появились**: `schema.sql` выполняется только на
  чистом томе. Выполните `docker compose down -v` и поднимите стенд заново.
- **Любой сценарий висит на `TRUNCATE`**: в базе остались подготовленные транзакции от `two_pc`.
  Сценарии сами откатывают их перед началом, но если вы прервали прогон вручную, выполните
  `two_pc_recover` или `docker compose down -v`.
- **`connection refused` на 55440**: порт занят другим сервером или стенд не поднят. Смените порт
  и задайте `SAGA_DSN`, как в разделе «Окружение».
