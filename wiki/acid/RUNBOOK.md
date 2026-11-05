# RUNBOOK: ACID-транзакции в PostgreSQL 18

Пошаговый прогон демо к статье [ACID](https://bigdataschool.ru/wiki/acid/). Один контейнер
PostgreSQL 18.6, пять сценариев, по одному на каждую букву ACID и ещё один отдельно на write
skew. Сценарии 1, 2 и 5 идут через `psql` из образа, сценарии 3 и 4 через две сессии Python
с явным чередованием шагов. Аномалии изоляции поэтому воспроизводятся каждый раз одинаково,
а не по таймингу.

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6` |
| Python | 3.10 или новее, проверено на 3.12.3 |
| psycopg | 3.3.8, `psycopg[binary]` с встроенной libpq 18 |
| Docker | с плагином Compose |

Сервер слушает `127.0.0.1:55435`, пользователь, пароль и база `demo`/`demo`/`acid`. Если порт
занят, поменяйте его в `docker-compose.yml` и задайте строку подключения для Python:
`export ACID_DSN="host=127.0.0.1 port=<порт> dbname=acid user=demo password=demo"`.

Весь прогон занимает около 15 секунд. Номера транзакций, LSN и pid у вас будут другими, всё
остальное совпадёт.

## Шаг 1. Поднять сервер и окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
docker compose exec -T pg psql -U demo -d acid -XAtc "SELECT version()"
```

Ожидаемо: `Container acid-pg  Healthy` и строка `PostgreSQL 18.6 ...`. Все сценарии разом
запускает `./acid_demo.sh all`, по одному `./acid_demo.sh atomicity` и так далее. Скрипт ищет
Python в `.venv/bin/python`, другой интерпретатор задаётся переменной `PY`.

## Шаг 2. Atomicity: всё или ничего

```bash
./acid_demo.sh atomicity
```

Перевод 30 от alice к bob. После первого `UPDATE` транзакция падает на `SELECT 1 / 0`, и
второй `UPDATE` сервер уже не принимает. Ожидаемо:

```
psql:/demo/sql/01_atomicity.sql:24: ERROR:  division by zero
psql:/demo/sql/01_atomicity.sql:26: ERROR:  current transaction is aborted, commands ignored until end of transaction block
COMMIT;
ROLLBACK
```

`COMMIT` в упавшей транзакции возвращает `ROLLBACK`: зафиксировать половину перевода нельзя
даже по ошибке. Балансы остались 100 и 50, статус транзакции `aborted`:

```
 failed_xid | status
------------+---------
 757        | aborted
```

Отменённая версия строки при этом не стёрта, а лежит на странице. Её не видно, потому что
создавшая её транзакция помечена отменённой:

```
 lp | t_xmin | t_xmax | t_ctid
----+--------+--------+--------
  1 |    756 |    757 | (0,3)
  2 |    756 |      0 | (0,2)
  3 |    757 |      0 | (0,3)
```

Строка 3 создана транзакцией 757, строка 1 ею же помечена удалённой. Для всех остальных
транзакций действует исходная строка 1. Место освободит `VACUUM`.

В конце `SAVEPOINT` откатывает ошибочный бонус в 1000 и сохраняет перевод на 10. Ожидаемо
`alice 90.00`, `bob 60.00`.

## Шаг 3. Consistency: только допустимые состояния

```bash
./acid_demo.sh consistency
```

У `accounts` есть `CHECK (balance >= 0)`, у `transfers` два внешних ключа на `accounts`,
объявленных как `DEFERRABLE INITIALLY IMMEDIATE`. Перевод 150 при балансе 100:

```
ERROR:  new row for relation "accounts" violates check constraint "accounts_balance_check"
DETAIL:  Failing row contains (1, alice, -50.00).
```

Отменяется вся транзакция, вместе с уже выполненной вставкой в `transfers` и зачислением bob:
балансы 100 и 50, `transfers_rows = 0`. Перевод на несуществующий счёт 99 падает сразу на
внешнем ключе.

После `SET CONSTRAINTS ALL DEFERRED` внешний ключ проверяется на `COMMIT`. Если счёт 3
создан до конца транзакции, `COMMIT` проходит. Если счёт 4 так и не появился, внутри
транзакции строка видна (`transfers_inside_txn = 2`), а ошибка приходит на `COMMIT`:

```
COMMIT;
ERROR:  insert or update on table "transfers" violates foreign key constraint "transfers_to_id_fkey"
DETAIL:  Key (to_id)=(4) is not present in table "accounts".
```

`CHECK` откладывать нельзя: `CHECK (x > 0) DEFERRABLE` сервер отвергает с ошибкой
`misplaced DEFERRABLE clause`. Откладываются только `UNIQUE`, `PRIMARY KEY`, `REFERENCES` и
`EXCLUDE`.

## Шаг 4. Isolation: чтения и потерянное обновление

```bash
./acid_demo.sh isolation
```

Строки с `[A]` и `[B]` показывают две сессии, `[admin]` третью, служебную. Ожидаемые ключевые
строки:

```
[A] BEGIN ISOLATION LEVEL READ UNCOMMITTED
[A] SHOW transaction_isolation
      -> [('read uncommitted',)]
[A] SELECT balance FROM accounts WHERE id = 1
      -> [('100.00',)]
```

B поставил баланс 0 и не зафиксировал. A на уровне Read Uncommitted этого не видит: в
PostgreSQL этот уровень работает как Read Committed, грязного чтения нет.

Дальше A дважды читает баланс alice и число счетов с балансом от 50, а между чтениями B
списывает 30 и добавляет счёт carol. На Read Committed второе чтение даёт `70.00` и `3`, то
есть неповторяемое и фантомное чтение. На Repeatable Read оба раза `100.00` и `2`: снимок
берётся на первом запросе транзакции и держится до конца.

Потерянное обновление: обе сессии читают 100, A пишет 110 и фиксирует, B пишет 120,
посчитанные в приложении. На Read Committed итог `120.00`, пополнение A потеряно. На Repeatable
Read запись B отвергается:

```
[B] UPDATE accounts SET balance = 120.00 WHERE id = 1
      !! SQLSTATE 40001 SerializationFailure: could not serialize access due to concurrent update
```

Повтор транзакции B целиком читает 110 и пишет 130, итог `130.00`.

## Шаг 5. Isolation: write skew

```bash
./acid_demo.sh write_skew
```

Инвариант «на дежурстве хотя бы один врач» не выражен ограничением схемы. Каждая сессия
считает дежурных и уходит, если их не меньше двух. Сессии меняют разные строки, поэтому
конфликта записи нет. На Repeatable Read обе транзакции фиксируются:

```
[admin] SELECT count(*) FILTER (WHERE on_call) AS on_call_now FROM doctors
      -> [(0,)]
```

На Serializable до фиксации видны предикатные блокировки SSI. Они ничего не блокируют,
только записывают, кто что читал:

```
-> [('A', 'relation', 'doctors', 'SIReadLock'), ('A', 'page', 'doctors_pkey', 'SIReadLock'),
    ('B', 'relation', 'doctors', 'SIReadLock'), ('B', 'page', 'doctors_pkey', 'SIReadLock')]
```

A фиксируется, B получает ошибку на `COMMIT`:

```
[B] COMMIT
      !! SQLSTATE 40001 SerializationFailure: could not serialize access due to read/write dependencies among transactions
```

Повтор B видит одного дежурного и остаётся, итог `on_call_now = 1`. Повторять нужно
транзакцию целиком, вместе с чтением: решение B принималось по устаревшему снимку.

## Шаг 6. Durability: коммит переживает сбой

```bash
./acid_demo.sh durability
```

Пять вставок, каждая в своей подтверждённой транзакции, при `synchronous_commit = on` и
`fsync = on`. Шестая вставка висит в открытой транзакции другой сессии, и в этот момент
сервер убивается `docker kill -s KILL` без контрольной точки. После рестарта в логе:

```
LOG:  database system was not properly shut down; automatic recovery in progress
LOG:  redo starts at 0/1BA1C50
LOG:  redo done at 0/1C7D290 system usage: CPU: user: 0.00 s, system: 0.00 s, elapsed: 0.00 s
LOG:  database system is ready to accept connections
```

И в таблице:

```
 committed_survived | uncommitted_survived
--------------------+----------------------
                  5 |                    0
```

Подтверждённые строки сервер восстановил по журналу предзаписи. Незафиксированная транзакция
до коммита не дошла и после восстановления считается отменённой, даже если её записи успели
попасть в журнал.

## Шаг 7. Убрать за собой

```bash
docker compose down -v
```

Ключ `-v` удаляет том с данными, повторный прогон начнётся с чистого кластера.

## Если не так

- **`FATAL: the database system is shutting down` на первом запросе.** Healthcheck без
  `-h 127.0.0.1` отвечает «готов», пока на чистом томе работает временный сервер `initdb`.
  В `docker-compose.yml` проверка уже идёт по TCP. Если вы её меняли, верните `-h 127.0.0.1`.
- **`connection refused` у Python на 55435.** Порт занят или контейнер не поднялся:
  `docker compose ps`. Другой порт задаётся в `docker-compose.yml` и в `ACID_DSN`.
- **`extension "pageinspect" is not available`.** Нужен образ с contrib-модулями. В
  официальном `postgres:18.6` они есть, в урезанных сборках может не быть.
- **Write skew на Serializable не ловится, обе транзакции фиксируются.** Проверьте, что обе
  сессии действительно открыты на `SERIALIZABLE`. SSI защищает, только когда на этом уровне
  работают все участники.
- **На Serializable ошибка пришла не на `COMMIT`, а на `UPDATE`.** Это тоже правильное
  поведение: сервер вправе прервать транзакцию в любой точке, где опознал опасную структуру
  зависимостей. Скрипт повторяет транзакцию в обоих случаях.
- **`ModuleNotFoundError: No module named 'psycopg'`.** Скрипт взял не тот интерпретатор:
  `PY=.venv/bin/python ./acid_demo.sh all`.
