#!/usr/bin/env bash
# postgres 18.6 в Docker, pgbench и pg_waldump из того же образа, прогнано на стенде 2026-11-05
# Пять сценариев WAL по очереди: ./wal_demo.sh all  или  ./wal_demo.sh lsn|fpw|commit|slot|crash
set -uo pipefail
cd "$(dirname "$0")" || exit 1

PSQL="docker compose exec -T pg psql -U demo -d waldemo -v ON_ERROR_STOP=1 -X"
PGBENCH_SECONDS=${PGBENCH_SECONDS:-10}

lsn() {
  # 1. LSN, сегменты и объём журнала
  $PSQL -f /demo/sql/01_lsn_volume.sql
}

fpw() {
  # 2. полностраничные образы после контрольной точки
  $PSQL -f /demo/sql/02_full_page_writes.sql
}

commit() {
  # 3. цена надёжного коммита: synchronous_commit on против off на одном клиенте
  $PSQL -c "DROP TABLE IF EXISTS bench_commits" \
        -c "CREATE TABLE bench_commits (id bigint GENERATED ALWAYS AS IDENTITY, payload text)"
  for mode in on off; do
    echo "--- synchronous_commit = $mode, ${PGBENCH_SECONDS} с, 1 клиент"
    $PSQL -qc "SELECT pg_stat_reset_shared('io')" >/dev/null
    # PGOPTIONS задаёт параметр для сеансов pgbench, сервер не перезапускается
    docker compose exec -T -e PGOPTIONS="-c synchronous_commit=$mode" pg \
      pgbench -U demo -d waldemo -n -c 1 -T "$PGBENCH_SECONDS" -f /demo/insert.sql \
      | grep -E "transactions actually processed|latency average|tps ="
    $PSQL -f /demo/sql/03_commit_io.sql
  done
}

slot() {
  # 4. брошенный слот репликации и рост pg_wal
  $PSQL -f /demo/sql/04_slot_retention.sql
}

crash() {
  # 5. аварийная остановка без контрольной точки и восстановление по журналу
  $PSQL -f /demo/sql/05_before_crash.sql
  local since
  since=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  echo "--- docker kill -s KILL wal-pg: postmaster убит без shutdown checkpoint"
  docker kill -s KILL wal-pg >/dev/null
  docker compose up -d --wait 2>&1 | tail -n 1
  echo "--- лог сервера после рестарта"
  docker logs --since "$since" wal-pg 2>&1 \
    | grep -E "interrupted|not properly shut down|redo starts|redo done|checkpoint complete|ready to accept" \
    | sed -E 's/^[0-9-]+ [0-9:.]+ UTC \[[0-9]+\] //'
  $PSQL -f /demo/sql/05_after_crash.sql
}

case ${1:-all} in
  lsn|fpw|commit|slot|crash) "$1" ;;
  all)
    echo "=== 1. LSN и объём журнала ===";            lsn
    echo; echo "=== 2. Full-page writes ===";          fpw
    echo; echo "=== 3. Цена надёжного коммита ===";    commit
    echo; echo "=== 4. Слот держит WAL ===";           slot
    echo; echo "=== 5. Восстановление после сбоя ==="; crash ;;
  *) echo "использование: $0 all|lsn|fpw|commit|slot|crash" >&2; exit 2 ;;
esac
