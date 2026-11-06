#!/usr/bin/env bash
# postgres 18.6 в Docker, psycopg 3.3.8, прогнано на стенде 2026-11-06
# Пять сценариев MVCC по очереди: ./mvcc_demo.sh all
# или по одному: ./mvcc_demo.sh versions|snapshot|hot|horizon|freeze
set -uo pipefail
cd "$(dirname "$0")" || exit 1

# -e печатает каждый запрос перед результатом, 2>&1 внутри контейнера держит ошибки рядом с запросом
psql_file() {
  docker compose exec -T pg sh -c "psql -U demo -d mvcc -X -e -v ON_ERROR_STOP=1 -f /demo/sql/$1 2>&1"
}
PY=${PY:-.venv/bin/python}

versions() { psql_file 01_versions.sql; }
snapshot() { "$PY" snapshot_demo.py snapshot; }
hot()      { psql_file 03_hot.sql; }
horizon()  { "$PY" snapshot_demo.py horizon; }
freeze()   { psql_file 05_freeze.sql; }

case ${1:-all} in
  versions|snapshot|hot|horizon|freeze) "$1" ;;
  all)
    rc=0
    echo "=== 1. Версии строки: xmin, xmax, ctid ===";              versions || rc=1
    echo; echo "=== 2. Снимок: чтение и запись не ждут друг друга ==="; snapshot || rc=1
    echo; echo "=== 3. HOT-обновления ===";                            hot      || rc=1
    echo; echo "=== 4. Горизонт удаления и VACUUM ===";                horizon  || rc=1
    echo; echo "=== 5. Возраст XID и заморозка ===";                   freeze   || rc=1
    exit $rc ;;
  *) echo "использование: $0 all|versions|snapshot|hot|horizon|freeze" >&2; exit 2 ;;
esac
