# OpenMetadata: демо к статье

Код к статье «OpenMetadata»: https://bigdataschool.ru/wiki/openmetadata/

Демо — реальный docker-compose стенд OpenMetadata 2.0.0, сканирование локальной PostgreSQL-базы
ingestion-фреймворком и чтение полученных метаданных двумя способами: классическим REST API
каталога и MCP Server, который в 2.0 включён по умолчанию.

## Файлы

| Файл | Что делает |
|---|---|
| `docker-compose-postgres.yml` | официальный стенд релиза 2.0.0: server, ingestion, Elasticsearch, PostgreSQL как metadata store |
| `ingest_postgres_metadata.py` | логин в OpenMetadata REST API, сканирование PostgreSQL-базы `MetadataWorkflow` из ingestion-фреймворка, запись через sink `metadata-rest` |
| `query_context_layer_mcp.py` | чтение тех же метаданных: сначала REST `search/query`, затем MCP Server (`POST /mcp`, JSON-RPC) — `tools/list`, `search_metadata`, `get_asset_context` |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Docker Desktop с Compose v2, минимум 6 GiB памяти и 4 vCPU у Docker. Python 3.12,
`openmetadata-ingestion==2.0.0`. Прогнано на macOS 26.5.2 (arm64), Docker 29.7.2.

## Как запустить

```bash
python3 -m pip install openmetadata-ingestion==2.0.0
docker compose -f docker-compose-postgres.yml up -d
python3 ingest_postgres_metadata.py
python3 query_context_layer_mcp.py
docker compose -f docker-compose-postgres.yml down
```

Подробности, ожидаемый вывод на каждом шаге и разбор граблей — в `RUNBOOK.md`.
