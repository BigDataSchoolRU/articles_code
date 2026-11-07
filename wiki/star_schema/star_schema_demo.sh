#!/usr/bin/env bash
# postgres 18.6 в Docker, прогнано на стенде 2026-11-07
# Все шаги по очереди: ./star_schema_demo.sh all
# или по одному: ./star_schema_demo.sh star|snowflake|queries|rename
set -uo pipefail
cd "$(dirname "$0")" || exit 1

# -e печатает каждый запрос перед результатом, 2>&1 внутри контейнера держит ошибки рядом с запросом
psql_file() {
  docker compose exec -T pg sh -c "psql -U demo -d dwh -X -e -v ON_ERROR_STOP=1 -f /demo/sql/$1 2>&1"
}

star()      { psql_file 01_star.sql; }
snowflake() { psql_file 02_snowflake.sql; }
queries()   { psql_file 03_queries.sql; }
rename()    { psql_file 04_rename.sql; }

case ${1:-all} in
  star|snowflake|queries|rename) "$1" ;;
  all)
    rc=0
    echo "=== 1. Star schema: факт и денормализованные измерения ==="; star      || rc=1
    echo; echo "=== 2. Snowflake schema на тех же данных ===";       snowflake || rc=1
    echo; echo "=== 3. Одна выборка на двух схемах ===";            queries   || rc=1
    echo; echo "=== 4. Цена переименования категории ===";         rename    || rc=1
    exit $rc ;;
  *) echo "использование: $0 all|star|snowflake|queries|rename" >&2; exit 2 ;;
esac
