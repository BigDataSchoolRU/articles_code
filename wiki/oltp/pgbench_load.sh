#!/usr/bin/env bash
# pgbench 18.6 из образа postgres:18.6, сценарий tpcb-like, прогнано на стенде 2026-11-03
# OLTP-нагрузка на PostgreSQL: TPS при 1, 4 и 16 клиентах и эффект горячей строки.
set -euo pipefail

CONTAINER=${CONTAINER:-oltp-postgres}
DB=oltp
DUR=${DUR:-20}   # секунд на каждый замер

# pgbench запускается внутри контейнера, отдельная установка не нужна
pgb() { docker exec -e PGPASSWORD=demo "$CONTAINER" pgbench -h localhost -U demo "$@"; }

# из длинного отчёта pgbench оставляем строки, которые сравниваем между замерами
summary() { grep -E '^(scaling factor|number of clients|number of transactions actually|number of failed|latency average|tps)'; }

# 1. Инициализация: scale 16 даёт 16 строк branches, 160 tellers и 1 600 000 accounts
echo "--- инициализация, scale 16 ---"
pgb -i -s 16 -q "$DB" 2>&1 | tail -n 1

# 2. Масштабирование по клиентам: каждая транзакция tpcb-like это 3 UPDATE, SELECT и INSERT
for c in 1 4 16; do
  j=$(( c < 4 ? c : 4 ))   # потоков pgbench не больше, чем ядер на стенде
  echo
  echo "--- tpcb-like, scale 16, клиентов $c ---"
  pgb -c "$c" -j "$j" -T "$DUR" "$DB" 2>&1 | summary
done

# 3. Горячая строка: при scale 1 в branches одна строка, и все 16 клиентов обновляют именно её
echo
echo "--- инициализация, scale 1 ---"
pgb -i -s 1 -q "$DB" 2>&1 | tail -n 1
echo
echo "--- tpcb-like, scale 1, клиентов 16 (горячая строка) ---"
pgb -c 16 -j 4 -T "$DUR" "$DB" 2>&1 | summary
