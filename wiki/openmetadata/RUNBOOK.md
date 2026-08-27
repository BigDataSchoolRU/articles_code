# RUNBOOK: OpenMetadata 2.0 — стенд, ingestion и MCP Server

Поднимает локальный стенд OpenMetadata 2.0.0 (server + Elasticsearch + PostgreSQL как metadata
store) через официальный docker-compose, сканирует реальную PostgreSQL-базу ingestion-фреймворком
и читает полученные метаданные двумя способами: классическим REST API каталога и MCP Server,
который в 2.0 включён по умолчанию.

## Окружение

- Docker Desktop с Docker Compose v2 (`docker compose version`)
- Python 3.12, venv с пакетом `openmetadata-ingestion==2.0.0` (`pip install openmetadata-ingestion==2.0.0`, тянет за собой `requests`)
- Источник для сканирования: любая PostgreSQL-база, до которой дотягивается Python-скрипт
  (в примерах ниже — `localhost:5432`, база `semantic_layer_demo`, пользователь без пароля,
  подставьте свои `hostPort` / `database` / `username` в `ingest_postgres_metadata.py`)
- Минимум 6 GiB памяти и 4 vCPU, выделенных Docker
- **Порт 5432 на хосте.** Если у вас уже что-то слушает `5432` (например локальный Postgres),
  в `docker-compose-postgres.yml` порт metadata-store контейнера уже перемаплен на `15432:5432` —
  внутри docker-сети сервисы всё равно ходят по 5432, конфликтует только хостовый порт.

## Шаг 1. Поднять стенд

```bash
docker compose -f docker-compose-postgres.yml up -d
```

Что должно быть в выводе: контейнеры `openmetadata_postgresql`, `openmetadata_elasticsearch`
переходят в `Healthy`, разовый контейнер `execute_migrate_all` завершается с кодом 0 и исчезает
из списка запущенных, следом стартуют `openmetadata_server` и `openmetadata_ingestion`.

Готовность API проверяется опросом:

```bash
until curl -s -o /dev/null -w "%{http_code}" http://localhost:8585/api/v1/system/version | grep -q 200; do sleep 5; done
curl -s http://localhost:8585/api/v1/system/version
```

Ожидаемый ответ: `{"version":"2.0.0",...}`. На типовой машине сервер поднимается за 1-2 минуты
после старта контейнера `openmetadata_server`.

UI по умолчанию: http://localhost:8585, логин `admin@open-metadata.org`, пароль `admin`.

## Шаг 2. Сканирование PostgreSQL-базы

```bash
python3 ingest_postgres_metadata.py
```

Что делает: логинится в OpenMetadata REST API дефолтным admin (получает свежий JWT на сессию),
запускает `MetadataWorkflow` ingestion-фреймворка на локальную PostgreSQL-базу и пишет результат
через sink `metadata-rest` в поднятый стенд.

Что должно быть в выводе: несколько строк `INFO ... Passed` (проверки доступа к источнику),
`Test connection for 'Postgres': Successful`, затем блок `Workflow ... Summary` с `Success %: 100.0`
и строка `Ingestion metadata workflow завершён успешно`. Ненулевой код возврата или исключение
в конце — значит шаг не прошёл.

## Шаг 3. Чтение метаданных: REST API и MCP Server

```bash
python3 query_context_layer_mcp.py
```

Что делает: тем же логином читает те же метаданные двумя способами — классическим
`GET /api/v1/search/query` и MCP-эндпоинтом `POST /mcp` (JSON-RPC, `tools/list` и
`tools/call`). MCP-приложение (`McpApplication`) в 2.0 включено по умолчанию, отдельно
активировать его в UI не нужно.

Что должно быть в выводе: раздел REST печатает найденный документ индекса, раздел MCP —
список инструментов (`search_metadata`, `get_asset_context` и другие) и в конце готовый
markdown-документ с схемой таблицы (колонки, типы, primary key) — это и есть то, что
получает AI-агент через MCP вместо разбора сырого JSON.

## Если не так

- **`execute_migrate_all` падает с `remaining connection slots are reserved for non-replication
  superuser connections`.** У образа `docker.getcollate.io/openmetadata/postgresql` по умолчанию
  `max_connections=20`, миграции этого не хватает. В `docker-compose-postgres.yml` у сервиса
  `postgresql` добавьте в `command` флаг `-c max_connections=200`, пересоздайте контейнер
  (`docker compose up -d postgresql`) и повторите `docker compose up -d`.
- **Контейнер `openmetadata_postgresql` не проходит healthcheck, в логах `database
  "openmetadata_db" does not exist`.** Инициализация БД была прервана на середине (например той
  же нехваткой соединений или прерыванием контейнера) и не успела создать прикладную базу.
  Полная переинициализация: `docker compose down`, удалить каталог bind-mount
  `docker-volume/db-data-postgres`, поднять стенд заново с нуля.
- **`ingest_postgres_metadata.py` падает на аутентификации к источнику.** Локальный Postgres с
  доверительной (trust) аутентификацией пароль не проверяет, но пустую строку коннектор не
  принимает — нужна любая непустая заглушка в `authType.password`.
- **В каталоге оказались служебные таблицы `information_schema.*`.** Без явного
  `schemaFilterPattern` коннектор Postgres по умолчанию сканирует и служебную схему. Фильтр
  нужно класть в `sourceConfig.config.schemaFilterPattern`, а не в `serviceConnection.config`
  (там тоже есть одноимённое поле, но оно не используется на этапе ингеста) — иначе фильтр
  молча не сработает. Если мусор уже успел попасть в каталог, `markDeletedTables` задним числом
  его не подчищает: проще удалить сервис (`DELETE /api/v1/services/databaseServices/name/<имя>
  ?hardDelete=true&recursive=true`) и просканировать заново.

## Погасить стенд

```bash
docker compose -f docker-compose-postgres.yml down
```

Данные остаются в `docker-volume/`, повторный `up -d` поднимет тот же каталог без пересканирования.
