# RUNBOOK: OLTP-нагрузка и конфликты транзакций на PostgreSQL

Пошаговый прогон демо к статье [OLTP](https://bigdataschool.ru/wiki/oltp/).

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6` |
| pgbench | 18.6, из того же образа |
| Python | 3.12 |
| psycopg | 3.3.7 (`psycopg[binary]`) |
| Docker | с плагином Compose |

Postgres слушает `127.0.0.1:55433`, пользователь, пароль и база `demo`/`demo`/`oltp`. Если порт
занят, поменяйте его в `docker-compose.yml` и задайте переменную
`PG_DSN=postgresql://demo:demo@127.0.0.1:<порт>/oltp`. Эталонный прогон сделан на 4 vCPU и 16 ГБ
памяти, контейнеру выделено 2 ГБ.

## Шаг 1. Поднять Postgres

```bash
docker compose up -d --wait
docker exec oltp-postgres postgres --version
docker exec oltp-postgres pgbench --version
```

Ожидаемо: `postgres (PostgreSQL) 18.6 ...` и `pgbench (PostgreSQL) 18.6 ...`. Флаг `--wait`
возвращает управление, когда healthcheck перешёл в `healthy`.

## Шаг 2. Нагрузка pgbench

```bash
./pgbench_load.sh
```

Скрипт инициализирует базу со scale 16 (16 строк `pgbench_branches`, 1 600 000 строк
`pgbench_accounts`), гоняет сценарий tpcb-like по 20 секунд при 1, 4 и 16 клиентах, затем
переинициализирует базу со scale 1 и снова даёт 16 клиентов. Длительность замера меняется
переменной `DUR`, например `DUR=60 ./pgbench_load.sh`. Весь шаг идёт около полутора минут.

Эталонный вывод (TPS на вашей машине будет другим, важна форма зависимости):

```
--- tpcb-like, scale 16, клиентов 1 ---
latency average = 10.042 ms
tps = 99.580371 (without initial connection time)

--- tpcb-like, scale 16, клиентов 4 ---
latency average = 16.307 ms
tps = 245.286641 (without initial connection time)

--- tpcb-like, scale 16, клиентов 16 ---
latency average = 32.882 ms
tps = 486.588358 (without initial connection time)

--- tpcb-like, scale 1, клиентов 16 (горячая строка) ---
latency average = 118.766 ms
tps = 134.718748 (without initial connection time)
```

Шаг прошёл, если во всех четырёх блоках `number of failed transactions: 0`, TPS растёт с числом
клиентов при scale 16 и заметно падает при scale 1 на тех же 16 клиентах.

## Шаг 3. Конфликт транзакций и повтор

```bash
python3 -m venv .venv
.venv/bin/pip install "psycopg[binary]==3.3.7"
.venv/bin/python serialization_retry.py
```

Ожидаемые строки:

```
--- сценарий 1, READ COMMITTED: два списания по 100 с баланса 1000 ---
T1 попытка 1: записала 900, COMMIT
итог: баланс 900, ожидалось 800

--- сценарий 1, REPEATABLE READ: два списания по 100 с баланса 1000 ---
T1 попытка 1: SQLSTATE 40001 could not serialize access due to concurrent update
T1 попытка 2: записала 800, COMMIT
итог: баланс 800, ожидалось 800

--- сценарий 2, REPEATABLE READ: alice и bob одновременно уходят с дежурства ---
итог: дежурных 0, правило требует не меньше 1

--- сценарий 2, SERIALIZABLE: alice и bob одновременно уходят с дежурства ---
T2: SQLSTATE 40001 could not serialize access due to read/write dependencies among transactions
итог: дежурных 1, правило требует не меньше 1
```

Шаг прошёл, если на READ COMMITTED одно списание потерялось, а на REPEATABLE READ и SERIALIZABLE
итог правильный после 40001.

## Шаг 4. Убрать стенд

```bash
docker compose down -v
```

## Если не так

- **`pgbench: error: connection to server ... failed`.** Контейнер ещё не готов. Запускайте после
  `docker compose up -d --wait` или проверьте `docker compose ps`.
- **TPS при 16 клиентах не выше, чем при 4.** Мало ядер или Docker ограничен по CPU. Это не
  ошибка демо, сравнивайте scale 1 и scale 16 на одном числе клиентов.
- **`psycopg.OperationalError: connection refused`.** Порт в `PG_DSN` не совпадает с портом в
  `docker-compose.yml`.
- **В сценарии 2 на SERIALIZABLE ошибка пришла не на COMMIT, а раньше.** PostgreSQL вправе
  прервать транзакцию на любом операторе, как только обнаружит опасную структуру зависимостей.
  Демо ловит `SerializationFailure` только на COMMIT, поэтому скрипт упадёт с трассировкой.
  Для PostgreSQL это штатное поведение. В рабочем коде повтор оборачивает транзакцию целиком,
  как в сценарии 1.
