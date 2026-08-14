# Change Data Capture (CDC)

Код к Wiki-статье «Change Data Capture (CDC)» на сайте BigDataSchool:
https://bigdataschool.ru/wiki/change_data_capture/

Демо показывает CDC без Debezium и Kafka: логическое декодирование PostgreSQL в чистом виде.
Видно, как INSERT, UPDATE и DELETE превращаются в события журнала, чем отличается
REPLICA IDENTITY FULL и сколько журнала удерживает непрочитанный слот репликации.

## Состав

- `cdc_slot_demo.sql` — таблица-источник, слот репликации, три операции и чтение потока изменений
- `cdc_replica_identity.sql` — что меняется в событиях UPDATE и DELETE при REPLICA IDENTITY FULL
- `cdc_slot_lag.sql` — 200 тысяч строк при молчащем потребителе и замер удержанного WAL
- `RUNBOOK.md` — пошаговый прогон с проверками

Скрипты запускаются по порядку: второй и третий рассчитывают на таблицу и слот из первого.

## Окружение

- PostgreSQL 18.4, параметр `wal_level = logical`
- Плагин логического декодирования `test_decoding`, он идёт в стандартной поставке
- Клиент `psql` той же версии

## Как запустить

1. Выставить `wal_level = logical` и перезапустить сервер.
2. Создать базу `cdc_demo`.
3. Выполнить три скрипта по порядку через `psql -d cdc_demo -f <файл>`.

Подробности и ожидаемый вывод каждого шага в `RUNBOOK.md`.
