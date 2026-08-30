# Milvus

Код к статье [Milvus](https://bigdataschool.ru/wiki/milvus/) на Wiki BigDataSchool.

## Файлы

- `collection_setup.py` — создание коллекции в Milvus Lite, вставка документов с embeddings
  (Ollama `nomic-embed-text`), построение HNSW-индекса.
- `search_demo.py` — обычный ANN-поиск и поиск с фильтром по скалярному полю `category`.
- `RUNBOOK.md` — пошаговый прогон демо с нуля.

## Окружение

Python 3.12+, `pymilvus[milvus_lite]==2.6.16`, локальный Ollama с моделью `nomic-embed-text`.
Docker не нужен — Milvus Lite встраиваемый, данные хранятся в локальном файле.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install "pymilvus[milvus_lite]==2.6.16" ollama
ollama pull nomic-embed-text

./.venv/bin/python3 collection_setup.py
./.venv/bin/python3 search_demo.py
```

Подробности и разбор возможных ошибок — в `RUNBOOK.md`.
