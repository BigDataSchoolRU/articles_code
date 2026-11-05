# RUNBOOK: WAL в PostgreSQL 18 изнутри

Пошаговый прогон демо к статье [WAL](https://bigdataschool.ru/wiki/write_ahead_log/). Один
контейнер PostgreSQL 18.6, пять сценариев: позиция и объём журнала, полностраничные образы,
цена надёжного коммита, слот репликации, восстановление после сбоя. Python не нужен:
`psql`, `pgbench` и `pg_waldump` берутся из образа.

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6` |
| pgbench, pg_waldump | 18.6, из того же образа |
| Docker | с плагином Compose |

Сервер слушает `127.0.0.1:55434`, пользователь, пароль и база `demo`/`demo`/`waldemo`. Порт
нужен только для подключения своим клиентом: сценарии ходят в контейнер через
`docker compose exec`. Если порт занят, поменяйте его в `docker-compose.yml`.

Параметры сервера заданы в `docker-compose.yml`: `max_wal_size=64MB` (по умолчанию 1 ГБ),
чтобы контрольные точки по объёму журнала случались на маленькой нагрузке, и
`checkpoint_timeout=30min`, чтобы плановая контрольная точка не вмешалась в сценарий сбоя.

Цифры ниже сняты на 4 vCPU и сетевом SSD облачной машины. Байты журнала в сценариях 1, 2 и 4
от железа не зависят, TPS в сценарии 3 зависит от задержки fsync вашего диска.

## Шаг 1. Поднять сервер

```bash
docker compose up -d --wait
docker compose exec -T pg psql -U demo -d waldemo -XAtc "SELECT version()"
```

Ожидаемо: `Container wal-pg  Healthy` и строка `PostgreSQL 18.6 ...`. Все сценарии разом:
`./wal_demo.sh all`, по одному: `./wal_demo.sh lsn` и так далее.

## Шаг 2. LSN и объём журнала

```bash
./wal_demo.sh lsn
```

Скрипт запоминает `pg_current_wal_lsn()` до и после вставки 100 тыс. строк и считает разность
через `pg_wal_lsn_diff`. Ожидаемо:

```
 wal_segment_size: 16MB
lsn_before = 0/1BE3BF8, сегмент 000000010000000000000001
lsn_after = 0/29DC8F8, сегмент 000000010000000000000002
 wal_written | table_with_index
 14 MB       | 7336 kB
 wal_written_unlogged: 0 bytes
 wal_records | wal_fpi | wal_bytes
      200544 |      45 | 14 MB
```

Журнала записано почти вдвое больше, чем весит таблица с индексом: каждая строка даёт запись
вставки в кучу и запись вставки в индекс (200 544 записи на 100 000 строк). Та же вставка в
UNLOGGED-таблицу журнал не трогает. Точные LSN у вас будут другими, порядок цифр тот же.

## Шаг 3. Полностраничные образы

```bash
./wal_demo.sh fpw
```

После `CHECKPOINT` один и тот же UPDATE одной строки выполняется дважды под
`EXPLAIN (ANALYZE, WAL)`, затем `pg_waldump` разбирает записи между двумя LSN. Ожидаемо:

```
 data_checksums: on
   WAL: records=1 fpi=2 bytes=12386      <- первый UPDATE после CHECKPOINT
   WAL: records=2 bytes=128              <- тот же UPDATE ещё раз
rmgr: Heap len (rec/tot): 78/ 12386 ... HOT_UPDATE ... blk 0 FPW, ... fork vm blk 0 FPW
rmgr: Heap len (rec/tot): 70/    70 ... HOT_UPDATE ... blk 0
   WAL: records=1 fpi=2 bytes=1446       <- первый UPDATE после CHECKPOINT с wal_compression = lz4
```

Первое изменение страницы после контрольной точки пишет её полный образ: страницу кучи и
страницу карты видимости (`FPW` у обоих блоков). Повторное изменение до следующей контрольной
точки пишет 70 байт. Сжатие lz4 уменьшает тот же образ в 8.6 раза.

Таблица создана с `fillfactor = 50`, а перед замером идёт `VACUUM`. Без этого UPDATE уезжает на
другую страницу, а чтение проставляет hint-биты, и из-за включённых по умолчанию в PostgreSQL 18
контрольных сумм они тоже пишутся в журнал образом страницы. Цифры смешиваются.

## Шаг 4. Цена надёжного коммита

```bash
./wal_demo.sh commit
```

pgbench 10 секунд гоняет одну вставку на транзакцию в одном клиенте, сначала при
`synchronous_commit = on`, потом при `off` (через `PGOPTIONS`, без перезапуска сервера). После
каждого прогона выводятся строки `pg_stat_io` по журналу. Ожидаемо:

```
--- synchronous_commit = on
tps = 149.7
 client backend | normal |   1497 |   1497      <- writes, fsyncs
--- synchronous_commit = off
tps = 4163.8
 walwriter      | normal |     55 |     52
```

При `on` каждый COMMIT ждёт свой fsync журнала: число fsync совпадает с числом транзакций, а
задержка коммита равна задержке fsync диска. При `off` клиент не ждёт, журнал сбрасывает
walwriter раз в `wal_writer_delay` (200 мс), за 10 секунд около 50 fsync. Разница в TPS на
вашем диске будет другой, NVMe с низкой задержкой fsync даст меньший разрыв.

## Шаг 5. Брошенный слот держит WAL

```bash
./wal_demo.sh slot
```

Ожидаемо:

```
--- 1. без слота
 wal_generated: 163 MB
 segments | pg_wal_size:  4 | 64 MB
--- 2. физический слот, к которому никто не подключился
 wal_generated: 163 MB
 segments | pg_wal_size: 11 | 176 MB
 lagging_replica | f | 0/D8965A8 | extended |
--- 3. потолок для слотов: max_slot_wal_keep_size = 32MB
 segments | pg_wal_size:  4 | 64 MB
 lagging_replica | f |  | lost | wal_removed
```

Без слота контрольная точка удаляет и переиспользует сегменты, и `pg_wal` держится в пределах
`max_wal_size`. Слот с `immediately_reserve = true` фиксирует `restart_lsn`, и сегменты после
него не удаляются, `pg_wal` выходит за `max_wal_size`, статус слота `extended`. Потолок
`max_slot_wal_keep_size` разрешает контрольной точке удалить лишнее, слот при этом становится
`lost` и для реплики больше не годится. Слот и настройка в конце возвращаются в исходное.

## Шаг 6. Восстановление после сбоя

```bash
./wal_demo.sh crash
```

Скрипт делает контрольную точку, пять подтверждённых транзакций по 2000 строк в обычную
таблицу и 10 000 строк в UNLOGGED-таблицу, затем убивает postmaster сигналом KILL и поднимает
контейнер заново. Ожидаемо:

```
 checkpoint_lsn |  redo_lsn
 0/17BD6558     | 0/17BD6500
 payments | payments_unlogged
    10000 |             10000
LOG:  database system was interrupted; last known up at ...
LOG:  database system was not properly shut down; automatic recovery in progress
LOG:  redo starts at 0/17BD6500
LOG:  redo done at 0/17D1A780 system usage: ... elapsed: 0.02 s
LOG:  database system is ready to accept connections
 payments | payments_unlogged | payments_sum
    10000 |                 0 |       100000
```

Проигрывание начинается ровно с `redo_lsn` последней контрольной точки. Все подтверждённые
строки на месте, хотя страницы данных на диск после контрольной точки не писались. UNLOGGED-таблица
после сбоя пуста: её изменений в журнале нет, и при восстановлении она обнуляется. В выводе
лога могут оказаться и строки `checkpoint complete` от контрольных точек прямо перед сбоем:
фильтр по времени у `docker logs` идёт с точностью до секунды.

## Шаг 7. Погасить

```bash
docker compose down -v
```

`-v` удаляет том с данными, следующий запуск начнёт с чистого `initdb`.

## Если не так

- **`FATAL: the database system is shutting down` на первом же psql.** Healthcheck без
  `-h 127.0.0.1` отвечает «готов» ещё во время `initdb`. В `docker-compose.yml` он уже с `-h`,
  не убирайте его.
- **В сценарии 3 TPS при `on` и `off` почти одинаковые.** Диск или виртуализация отвечают на
  fsync мгновенно (кэш записи без сброса, `fsync = off` в своём конфиге). Проверьте
  `SHOW fsync` и что база лежит не на tmpfs.
- **В сценарии 2 у первого UPDATE `fpi=0`.** Между `CHECKPOINT` и UPDATE страница уже менялась.
  Запускайте `./wal_demo.sh fpw` целиком, он сам пересоздаёт таблицу.
- **В сценарии 4 `pg_wal` не вырос.** Слот создан без резервирования: второй аргумент
  `pg_create_physical_replication_slot` должен быть `true`, иначе `restart_lsn` пуст до
  первого подключения реплики.
- **Порт 55434 занят.** Поменяйте левую часть в `ports:` или удалите секцию, сценариям порт не нужен.
