# RUNBOOK: MVCC в PostgreSQL 18

Пошаговый прогон демо к статье [MVCC](https://bigdataschool.ru/wiki/mvcc/). Один контейнер
PostgreSQL 18.6 и пять сценариев: версии строки, снимок, HOT-обновления, горизонт удаления и
заморозка. Сценарии 1, 3 и 5 идут через `psql` из образа. Сценарии 2 и 4 запускаются через
две сессии Python с явным чередованием шагов, поэтому результат не зависит от таймингов.

На всех демо-таблицах выключен автовакуум (`autovacuum_enabled = off`). Иначе фоновый процесс
может убрать мёртвые версии между шагами, и картина на странице поменяется.

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6`, контрольные суммы страниц включены (умолчание initdb с 18) |
| Расширения | `pageinspect` и `pg_visibility` из contrib, в образе есть |
| Python | 3.10 или новее, проверено на 3.12.3 |
| psycopg | 3.3.8, `psycopg[binary]` с встроенной libpq 18 |
| Docker | с плагином Compose |

Сервер слушает `127.0.0.1:55436`, пользователь, пароль и база `demo`/`demo`/`mvcc`. Если порт
занят, поменяйте его в `docker-compose.yml` и задайте строку подключения для Python:
`export MVCC_DSN="host=127.0.0.1 port=<порт> dbname=mvcc user=demo password=demo"`.

Весь прогон занимает около 15 секунд. Номера транзакций (XID) и `filenode` у вас будут
другими, всё остальное совпадёт. В выводе ниже XID взяты с чистого тома.

## Шаг 1. Поднять сервер и окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
docker compose exec -T pg psql -U demo -d mvcc -XAtc "SELECT version()"
```

Ожидаемо: `Container mvcc-pg  Healthy` и строка `PostgreSQL 18.6 ...`. Все сценарии разом
запускает `./mvcc_demo.sh all`, по одному `./mvcc_demo.sh versions` и так далее. Скрипт ищет
Python в `.venv/bin/python`, другой интерпретатор задаётся переменной `PY`.

## Шаг 2. Версии строки: xmin, xmax, ctid

```bash
./mvcc_demo.sh versions
```

Строка вставляется транзакцией 756 и обновляется транзакцией 757. Запрос видит одну строку,
а на странице лежат две версии:

```
 lp | lp_flags | t_xmin | t_xmax | t_ctid | raw_flags
  1 |        1 |    756 |    757 | (0,2)  | {HEAP_HASVARWIDTH,HEAP_XMIN_COMMITTED,HEAP_XMAX_COMMITTED,HEAP_HOT_UPDATED}
  2 |        1 |    757 |      0 | (0,2)  | {HEAP_HASVARWIDTH,HEAP_XMIN_COMMITTED,HEAP_XMAX_INVALID,HEAP_UPDATED,HEAP_ONLY_TUPLE}
```

Как понять, что шаг прошёл:

- у старой версии `t_xmax` равен XID обновления, а `t_ctid` указывает на новую версию `(0,2)`;
- сразу после `COMMIT`, до первого чтения, у старой версии ещё нет флага `XMAX_COMMITTED`, а у
  новой нет `XMIN_COMMITTED`. Это подсказки (hint bits), которые проставляет первый же запрос,
  увидевший итог транзакции: во втором выводе страницы оба флага уже стоят;
- DELETE с откатом оставляет `xmax 758`, но строка видна, а `pg_xact_status` отвечает `aborted`;
- после DELETE с коммитом `visible_rows 0`, а обе версии по-прежнему лежат на странице.

## Шаг 3. Снимок: чтение и запись не ждут друг друга

```bash
./mvcc_demo.sh snapshot
```

Ожидаемо в 2.1 (Repeatable Read):

```
[A] SELECT pg_current_snapshot()
      -> [('763:763:',)]
[A] SELECT pg_current_xact_id_if_assigned()
      -> [(None,)]
[B] UPDATE accounts SET balance = 70 WHERE id = 1
      (выполнено за 1.1 мс)
[A] SELECT balance FROM accounts WHERE id = 1
      -> [('100.00',)]
      (выполнено за 0.3 мс)
[B] COMMIT
[A] SELECT balance FROM accounts WHERE id = 1
      -> [('100.00',)]
```

- ни UPDATE в B, ни SELECT в A не ждут друг друга, оба идут за миллисекунды;
- читающая транзакция A номер не получает (`None`), XID выдаётся при первой записи;
- снимок A после коммита B не меняется, A видит `100.00` до своего `COMMIT`, затем `70.00`.

Ожидаемо в 2.2 (Read Committed):

```
[A] SELECT balance, pg_current_snapshot() FROM accounts WHERE id = 1
      -> [('70.00', '764:766:764')]
[B] COMMIT
[A] SELECT balance, pg_current_snapshot() FROM accounts WHERE id = 1
      -> [('40.00', '766:766:')]
```

Снимок записан как `xmin:xmax:список активных`. Пока B (764) не зафиксирована, она стоит в
списке активных, и её версия не видна. Следующий оператор той же транзакции A берёт новый
снимок и видит `40.00`.

## Шаг 4. HOT-обновления

```bash
./mvcc_demo.sh hot
```

Три обновления неиндексированной колонки `qty` у строки 1 и одно обновление индексированной
`sku` у строки 2:

```
 lp | lp_flags | t_xmin | t_xmax | t_ctid | raw_flags
  1 |        1 |    768 |    769 | (0,3)  | {...,HEAP_HOT_UPDATED}
  2 |        1 |    768 |    772 | (0,6)  | {...}
  3 |        1 |    769 |    770 | (0,4)  | {...,HEAP_UPDATED,HEAP_HOT_UPDATED,HEAP_ONLY_TUPLE}
  4 |        1 |    770 |    771 | (0,5)  | {...,HEAP_UPDATED,HEAP_HOT_UPDATED,HEAP_ONLY_TUPLE}
  5 |        1 |    771 |      0 | (0,5)  | {...,HEAP_UPDATED,HEAP_ONLY_TUPLE}
  6 |        1 |    772 |      0 | (0,6)  | {...,HEAP_UPDATED}
```

В первичном ключе на строку 1 одна запись `(0,1)`, на строку 2 две: `(0,2)` и `(0,6)`. После
`VACUUM` указатель 1 становится перенаправлением (`lp_flags 2`), а 2, 3 и 4 освобождаются
(`lp_flags 0`).

Сравнение `fillfactor` на 2000 одинаковых строк, обновлены пять строк с первой страницы:

```
  tbl  | pages | page0_free_bytes
 ff100 |    25 |               68
 ff90  |    28 |              868

 ff100 | {"(24,57)","(24,58)","(24,59)","(24,60)","(24,61)"}
 ff90  | {"(0,74)","(0,75)","(0,76)","(0,77)","(0,78)"}

 relname  | n_tup_upd | n_tup_hot_upd | n_tup_newpage_upd
 ff100    |         5 |             0 |                 5
 ff90     |         5 |             5 |                 0
 hot_demo |         4 |             3 |                 0
```

## Шаг 5. Горизонт удаления и VACUUM

```bash
./mvcc_demo.sh horizon
```

Сессия H открывает транзакцию Repeatable Read и читает таблицу на 100 000 строк, сессия W
переписывает все строки. Ожидаемо:

```
[admin] SELECT application_name, state, backend_xmin, age(backend_xmin) AS xmin_age FROM pg_stat_activity ...
      -> [('session_H', 'idle in transaction', '781', 1)]
[W] VACUUM (VERBOSE) events
      INFO tuples: 0 removed, 200000 remain, 100000 are dead but not yet removable
      INFO removable cutoff: 781, which was 1 XIDs old when operation ended
      -> [(100000, 100000, '13 MB')]
[H] COMMIT
[W] VACUUM (VERBOSE) events
      INFO tuples: 100000 removed, 100000 remain, 0 are dead but not yet removable
      -> [(100000, 0, '13 MB')]
[admin] VACUUM FULL events
      -> [(16491, '6672 kB')]
```

- пока H открыта, горизонт удаления (`removable cutoff`) стоит на её `backend_xmin`, и все
  100 000 мёртвых версий VACUUM пропускает;
- после `COMMIT` в H тот же VACUUM удаляет их, но файл остаётся 13 MB: место освобождается
  внутри страниц для будущих версий;
- `VACUUM FULL` пишет таблицу в новый файл (другой `filenode`), размер возвращается к 6672 kB.

## Шаг 6. Возраст XID и заморозка

```bash
./mvcc_demo.sh freeze
```

Сначала печатаются пороги сервера (значения по умолчанию в 18.6):

```
 autovacuum_freeze_max_age            | 200000000
 autovacuum_vacuum_insert_threshold   | 1000
 autovacuum_vacuum_max_threshold      | 100000000
 autovacuum_vacuum_scale_factor       | 0.2
 autovacuum_vacuum_threshold          | 50
 vacuum_failsafe_age                  | 1600000000
 vacuum_freeze_min_age                | 50000000
 vacuum_freeze_table_age              | 150000000
 vacuum_max_eager_freeze_failure_rate | 0.03
```

После тысячи транзакций возраст таблицы `1002`. После `VACUUM (FREEZE)`:

```
 relfrozenxid | table_xid_age
         1787 |             0

 lp | t_xmin |   combined_flags   | raw_flags
  1 |    785 | {HEAP_XMIN_FROZEN} | {HEAP_HASVARWIDTH,HEAP_XMIN_COMMITTED,HEAP_XMIN_INVALID,HEAP_XMAX_INVALID}

 all_visible | all_frozen
           6 |          6
```

`t_xmin` у версии остаётся прежним, замороженной её делает пара флагов `XMIN_COMMITTED` и
`XMIN_INVALID`. Все шесть страниц помечены в карте видимости как all-visible и all-frozen.

## Шаг 7. Убрать стенд

```bash
docker compose down -v
```

## Если не так

- **`Container mvcc-pg  Error` или порт занят.** Поменяйте порт в `docker-compose.yml` и
  задайте `MVCC_DSN`, как в разделе «Окружение».
- **`FATAL: the database system is shutting down` на первом запросе.** Healthcheck без
  `-h 127.0.0.1` отвечает «готов» ещё во время `initdb`. В `docker-compose.yml` проверка уже идёт
  по TCP; если вы её меняли, верните `-h 127.0.0.1`.
- **`n_dead_tup` или `n_tup_hot_upd` равны нулю, хотя обновления прошли.** Счётчики сессии
  уходят в общую память с задержкой. Демо вызывает `pg_stat_force_next_flush()` перед чтением
  статистики; в своих экспериментах делайте так же или подождите секунду.
- **В шаге 6 `all_visible 0` и `all_frozen 0` после `VACUUM (FREEZE)`, хотя версии заморожены.**
  Так бывает, если прямо перед VACUUM шли транзакции, которые получили XID и ничего не записали.
  Их коммит сбрасывается в журнал фоном, в пределах `wal_writer_delay` (200 мс). Демо поэтому
  ждёт секунду перед VACUUM; повторный VACUUM тоже помечает страницы.
- **В шаге 5 мёртвые версии не удаляются и после `COMMIT` в H.** Горизонт держит другая
  открытая транзакция или слот репликации. Найдите её запросом к `pg_stat_activity` по
  `backend_xmin`, как в демо, и проверьте `pg_replication_slots`.
- **Номера XID другие.** Это нормально: на непустом томе счётчик транзакций уже ушёл вперёд.
