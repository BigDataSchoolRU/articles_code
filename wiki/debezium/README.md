# Debezium

Код к Wiki-статье «Debezium» на сайте BigDataSchool: https://bigdataschool.ru/wiki/debezium/

## Состав
- `docker-compose.yml` — PostgreSQL 18 с wal_level=logical и Debezium Server 3.6.1.Final
- `init.sql` — таблица orders и две строки для начального снимка
- `config/application.properties` — конфигурация коннектора, формат конверта before и after
- `config/application_full.properties` — второй прогон: decimal.handling.mode и SMT unwrap
- `event_sink.py` — HTTP-приёмник событий, пишет JSONL и печатает в консоль
- `workload.sql`, `workload2.sql` — INSERT, UPDATE и DELETE для генерации событий
- `RUNBOOK.md` — пошаговый прогон с проверками

## Окружение
Docker 29.4.2 с запущенным демоном, Python 3.12 для приёмника событий. Образы
`postgres:18` и `quay.io/debezium/server:3.6.1.Final` тянутся автоматически.

## Как запустить
1. Поднять приёмники событий: `python3 event_sink.py events.jsonl 8099` и
   `python3 event_sink.py events_full.jsonl 8100`
2. Поднять стенд: `docker compose up -d`
3. Дать нагрузку: `docker exec -i dbz_pg psql -U postgres -d shopdb < workload.sql`
4. Смотреть события в `events.jsonl`

Подробности и проверки после каждого шага в `RUNBOOK.md`.
