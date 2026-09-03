# RUNBOOK: PeerDB — CDC из PostgreSQL в ClickHouse

Поднимает self-hosted PeerDB v0.37.5 (Nexus, Flow API/Worker, Temporal, catalog-Postgres, MinIO)
и отдельный ClickHouse-приёмник, настраивает CDC-репликацию одной таблицы и показывает, как
PeerDB кладёт изменения в ClickHouse через `ReplacingMergeTree` — включая дубли до фонового merge
и два способа получить корректный текущий срез (`FINAL` и `argMax`).

## Окружение

- Linux или macOS, Docker Engine 24+ и Docker Compose v2 (проверено на Docker 29.1.3 / Compose v5.3.1)
- `git`, `psql` (клиент PostgreSQL, любая современная версия — проверено на 16.15), `curl`, `bc`
- Свободные порты на хосте: `9900`, `9901`, `7233`, `8085`, `8112`, `8113`, `9001`, `9002`, `3001`,
  `8124`, `9010`. Если какой-то занят другим сервисом — поправьте `ports:` в соответствующем
  compose-файле до старта, PeerDB и ClickHouse от конкретных портов не зависят.
- Ресурсы: весь стек (10 контейнеров) укладывается в 2 ГБ RAM в простое.

## Шаг 1. Поднять self-hosted PeerDB

```bash
git clone --depth 1 https://github.com/PeerDB-io/peerdb.git peerdb-src
cd peerdb-src
cat > docker-compose.override.yml <<'EOF'
# порт 3000 у peerdb-ui часто занят другими веб-сервисами на хосте
services:
  peerdb-ui:
    ports:
      - 3001:3000
EOF
docker compose -f docker-compose.yml -f docker-compose.override.yml pull
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  up -d --no-attach catalog --no-attach temporal --no-attach temporal-ui --no-attach temporal-admin-tools
```

**Проверка.** `docker ps` показывает 10 запущенных контейнеров, среди них `catalog`, `temporal`,
`peerdb-server`, `flow_api`, `flow-worker`. Если что-то в статусе `Restarting` — смотрите `docker
logs <имя>`, обычно это конфликт порта на хосте.

## Шаг 2. Поднять ClickHouse-приёмник

Официальный docker-compose PeerDB ClickHouse не включает — добавляем отдельным файлом в ту же
docker-сеть `peerdb_network`, которую создал шаг 1.

```bash
cd ..
mkdir -p clickhouse_data
# скопируйте сюда clickhouse_target_compose.yml из этого репозитория
docker compose -f clickhouse_target_compose.yml up -d
```

**Проверка.**

```bash
curl -s -u peerdb:peerdb_demo_pass 'http://localhost:8124/' --data-binary 'SELECT version()'
```

Должна вернуться версия ClickHouse (`26.3...`). Если curl виснет или возвращает пусто — контейнер
`peerdb-clickhouse-target` ещё стартует, подождите несколько секунд.

## Шаг 3. Создать источник данных

```bash
psql 'postgresql://postgres:postgres@localhost:9901/postgres' -f source_schema.sql
```

**Проверка.** Последняя строка вывода — `INSERT 0 20`.

## Шаг 4. Настроить peer'ы и mirror через Nexus

```bash
psql 'postgresql://postgres:peerdb@localhost:9900/postgres' -f peerdb_mirror.sql
```

**Проверка.** Три строки вывода: `OK`, `OK`, `CREATE MIRROR orders_cdc`. Если вместо этого ошибка
`table ... exists and is not empty` — в ClickHouse уже есть таблица от предыдущего прогона, удалите
её (`DROP TABLE peerdb_target.\`peerdb_target.orders_cdc\``) и повторите шаг.

## Шаг 5. Прогнать демонстрацию CDC

```bash
chmod +x cdc_dedup_demo.sh
./cdc_dedup_demo.sh
```

**Что должно быть в выводе.** Пункт 1 — снапшот из 20 строк виден в ClickHouse за доли секунды —
секунды. Пункт 3 — четыре изменения из источника (2 UPDATE, 1 DELETE, 1 INSERT) долетают до
ClickHouse батчем, на этом стенде задержка была около 10 секунд — это интервал синхронизации
CDC-батча в PeerDB по умолчанию, не задержка сети. Пункт 4 — по изменённым id видно и старую,
и новую версию строки (у удалённой — с `_peerdb_is_deleted = 1`), потому что `ReplacingMergeTree`
не переписывает данные на месте. Пункт 5 — naive `count()` в этот момент завышен (24 вместо 20),
а `FINAL` и `argMax` дают одинаковый правильный результат — 20.

## Если что-то пошло не так

- **`DB::NetException: Not found address of host: host.docker.internal (DNS_ERROR)`** при первом
  прогоне mirror — в `clickhouse_target_compose.yml` не хватает блока `extra_hosts:
  ["host.docker.internal:host-gateway"]`. Без него ClickHouse не может обратиться к
  MinIO-стейджингу PeerDB, который слушает на хосте. Добавьте блок, пересоздайте контейнер
  (`docker compose -f clickhouse_target_compose.yml up -d --force-recreate`) и повторите шаг 4.
- **`ERROR: num_rows_per_partition is required`** при попытке `CREATE MIRROR ... FOR $$SELECT ...
  $$` — это синтаксис batch-репликации по запросу (QRep), а не CDC. Для потоковой CDC-репликации
  таблицы нужен синтаксис `CREATE MIRROR ... WITH TABLE MAPPING (схема.таблица:схема.таблица)`,
  как в `peerdb_mirror.sql`.
- **`unable to drop peer: ... currently involved in an ongoing mirror`** при попытке удалить peer
  сразу после `DROP MIRROR` — остановка workflow в Temporal занимает несколько секунд. Подождите
  5-10 секунд и повторите `DROP PEER`.
- **Порт `3000` уже занят** — это порт `peerdb-ui` по умолчанию, `docker-compose.override.yml` из
  шага 1 переносит его на `3001`. Если заняты другие порты из списка выше — правьте `ports:`
  аналогично в нужном compose-файле.
