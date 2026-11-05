#!/usr/bin/env bash
# postgres 18.6 в Docker, psycopg 3.3.8, прогнано на стенде 2026-11-05
# Пять сценариев ACID по очереди: ./acid_demo.sh all
# или по одному: ./acid_demo.sh atomicity|consistency|isolation|write_skew|durability
set -uo pipefail
cd "$(dirname "$0")" || exit 1

# -e печатает каждый запрос перед результатом, 2>&1 внутри контейнера держит ошибки рядом с запросом
psql_file() {
  docker compose exec -T pg sh -c "psql -U demo -d acid -X -e -v ON_ERROR_STOP=1 -f /demo/sql/$1 2>&1"
}
PY=${PY:-.venv/bin/python}

atomicity()   { psql_file 01_atomicity.sql; }
consistency() { psql_file 02_consistency.sql; }
isolation()   { "$PY" isolation_demo.py reads lost_update; }
write_skew()  { "$PY" isolation_demo.py write_skew; }

durability() {
  psql_file 05_before_crash.sql
  # незафиксированная транзакция висит в отдельной сессии в момент сбоя
  docker compose exec -T pg psql -U demo -d acid -X -q \
    -c "BEGIN; INSERT INTO orders (note) VALUES ('не зафиксирован'); SELECT pg_sleep(120);" \
    >/dev/null 2>&1 &
  local bg=$!
  for _ in $(seq 30); do
    n=$(docker compose exec -T pg psql -U demo -d acid -XAtc \
      "SELECT count(*) FROM pg_stat_activity WHERE state = 'active' AND query LIKE '%pg_sleep(120)%' AND pid <> pg_backend_pid()")
    [ "$n" = 1 ] && break
    sleep 1
  done
  echo "--- сессий с открытой транзакцией и вставкой: $n"
  local since
  since=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  echo "--- docker kill -s KILL acid-pg: сервер убит без контрольной точки"
  docker kill -s KILL acid-pg >/dev/null
  wait "$bg" 2>/dev/null
  docker compose up -d --wait 2>&1 | tail -n 1
  echo "--- лог сервера после рестарта"
  docker logs --since "$since" acid-pg 2>&1 \
    | grep -E "interrupted|not properly shut down|redo starts|redo done|ready to accept" \
    | sed -E 's/^[0-9-]+ [0-9:.]+ UTC \[[0-9]+\] //'
  psql_file 05_after_crash.sql
}

case ${1:-all} in
  atomicity|consistency|isolation|write_skew|durability) "$1" ;;
  all)
    echo "=== 1. Atomicity ===";                  atomicity
    echo; echo "=== 2. Consistency ===";          consistency
    echo; echo "=== 3. Isolation: чтения и потерянное обновление ==="; isolation
    echo; echo "=== 4. Isolation: write skew ===";  write_skew
    echo; echo "=== 5. Durability ===";           durability ;;
  *) echo "использование: $0 all|atomicity|consistency|isolation|write_skew|durability" >&2; exit 2 ;;
esac
