# Semantic search

Код к Wiki-статье «Semantic search» на сайте BigDataSchool: https://bigdataschool.ru/wiki/semantic_search/

## Состав
- `search_comparison.py` - semantic search (cosine similarity по эмбеддингам nomic-embed-text) против наивного поиска по ключевым словам на корпусе обращений в техподдержку
- `RUNBOOK.md` - пошаговый прогон с проверками

## Окружение
Python 3.12, пакеты `ollama` 0.6.2 и `numpy` 2.5.2. Локальная Ollama 0.32.13 на http://localhost:11434 со скачанной моделью `nomic-embed-text`.

## Как запустить
1. `ollama pull nomic-embed-text` (если модели ещё нет)
2. `python3 -m pip install ollama numpy`
3. `python3 search_comparison.py`
