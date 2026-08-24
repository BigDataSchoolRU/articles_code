# Qdrant

Код к Wiki-статье «Qdrant» на сайте BigDataSchool: https://bigdataschool.ru/wiki/qdrant/

## Состав
- `docker-compose.yml` - Qdrant 1.19.0 на портах 6333 и 6334 с именованным томом под данные
- `qdrant_demo.py` - коллекция с квантованием, индекс по payload, векторный поиск с фильтром
- `RUNBOOK.md` - пошаговый прогон с проверками

## Окружение
Qdrant 1.19.0 в Docker, qdrant-client 1.19.0, Python 3.12, Ollama с моделью nomic-embed-text.
Должны быть свободны порты 6333 и 6334, Ollama доступна на http://localhost:11434.

## Как запустить
1. `docker compose up -d` и дождаться ответа `all shards are ready` на `curl -s http://localhost:6333/readyz`
2. `python3 -m pip install "qdrant-client==1.19.0"`
3. `python3 qdrant_demo.py`
4. `docker compose down` после прогона
