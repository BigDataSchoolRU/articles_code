#!/usr/bin/env bash
# bash + psql (клиент PostgreSQL 16) + curl, PeerDB v0.37.5, ClickHouse 26.3, прогнано на стенде 2026-09-03.
# Требует запущенных source_schema.sql и peerdb_mirror.sql (см. RUNBOOK.md).
#
# Показывает механизм: PeerDB льёт CDC в ClickHouse через ReplacingMergeTree, где UPDATE и DELETE
# не перезаписывают строку на месте, а добавляют новую версию (DELETE — с флагом _peerdb_is_deleted).
# Пока фоновый merge не прошёл, наивный SELECT видит дубли и удалённые строки как живые.
set -euo pipefail

SRC="postgresql://postgres:postgres@localhost:9901/source"
CH_TABLE='peerdb_target.`peerdb_target.orders_cdc`'
ch() { curl -s -u peerdb:peerdb_demo_pass 'http://localhost:8124/' --data-binary "$1"; }

echo "=== 1. Ждём начальный снапшот (20 строк) ==="
t0=$(date +%s.%N)
for _ in $(seq 1 60); do
    n=$(ch "SELECT count() FROM $CH_TABLE" || echo 0)
    [ "$n" = "20" ] && break
    sleep 0.5
done
t1=$(date +%s.%N)
echo "снапшот виден в ClickHouse через $(echo "$t1 - $t0" | bc)s, строк: $n"

echo
echo "=== 2. Меняем данные в источнике: 2 UPDATE, 1 DELETE, 1 INSERT ==="
t2=$(date +%s.%N)
psql "$SRC" -q -c "
UPDATE orders SET status='shipped', updated_at=now() WHERE id=1;
UPDATE orders SET amount=999.99, updated_at=now() WHERE id=2;
DELETE FROM orders WHERE id=3;
INSERT INTO orders (customer, amount, status) VALUES ('customer_21', 42.42, 'new');
"

echo
echo "=== 3. Ждём, пока CDC-батч долетит до ClickHouse (raw count меняется с 20) ==="
for _ in $(seq 1 60); do
    n=$(ch "SELECT count() FROM $CH_TABLE" || echo 20)
    [ "$n" != "20" ] && break
    sleep 0.5
done
t3=$(date +%s.%N)
echo "изменения видны в ClickHouse через $(echo "$t3 - $t2" | bc)s от коммита в источнике, raw-строк: $n"

echo
echo "=== 4. Наивный SELECT без FINAL: видны обе версии изменённых строк и \"живая\" удалённая ==="
ch "SELECT id, customer, amount, status, _peerdb_is_deleted, _peerdb_version FROM $CH_TABLE WHERE id IN (1,2,3) ORDER BY id, _peerdb_version FORMAT PrettyCompact"

echo
echo "=== 5. Три способа посчитать текущее число активных заказов ==="
echo "-- naive count(), до фонового merge завышает результат:"
ch "SELECT count() FROM $CH_TABLE"
echo
echo "-- FINAL + фильтр по _peerdb_is_deleted, схлопывает версии на чтении:"
ch "SELECT count() FROM $CH_TABLE FINAL WHERE _peerdb_is_deleted = 0"
echo
echo "-- argMax по _peerdb_version, не требует FINAL и дешевле на больших таблицах:"
ch "SELECT count() FROM (
        SELECT id, argMax(_peerdb_is_deleted, _peerdb_version) AS is_deleted
        FROM $CH_TABLE
        GROUP BY id
    ) WHERE is_deleted = 0"
echo

echo "=== КОНЕЦ ==="
