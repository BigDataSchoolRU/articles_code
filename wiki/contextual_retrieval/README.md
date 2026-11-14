# Contextual Retrieval

Код к статье Wiki BigDataSchool: https://bigdataschool.ru/wiki/contextual_retrieval/

Локальная LLM дописывает к каждому чанку короткий контекст из документа (метод Anthropic
Contextual Retrieval), и доля неудачных извлечений сравнивается для векторного поиска, BM25 и
гибрида с RRF до и после контекстуализации.

## Состав

| Файл | Что внутри |
|---|---|
| `corpus.py` | шесть синтетических квартальных отчётов, 24 чанка и 12 запросов с эталонными чанками |
| `contextualize.py` | контекст к каждому чанку через `qwen2.5:7b` с промптом из первоисточника, замер кэша префикса, запись в `contexts.json` |
| `index_search.py` | векторный индекс на `nomic-embed-text`, BM25 на bm25s и их слияние через Reciprocal Rank Fusion |
| `evaluate.py` | доля неудачных извлечений при k = 1, 3, 5 на голых чанках и на чанках с контекстом |
| `contexts.json` | контексты и счётчики токенов из прогона на стенде 2026-11-14 |
| `docker-compose.yml` | Ollama 0.40.13 в контейнере |
| `requirements.txt` | bm25s, PyStemmer, numpy с пинами версий |
| `RUNBOOK.md` | пошаговый запуск с ожидаемым выводом и типовыми проблемами |

## Окружение

Docker с Compose, Python 3.12, около 6 ГБ диска под модели и 8 ГБ свободной памяти. GPU не нужен:
на CPU весь прогон занимает около 10 минут.

## Запуск

```bash
docker compose up -d
docker exec contextual-retrieval-ollama ollama pull qwen2.5:7b
docker exec contextual-retrieval-ollama ollama pull nomic-embed-text
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -u contextualize.py
.venv/bin/python evaluate.py
```

`contexts.json` из нашего прогона лежит в репозитории: чтобы посмотреть только поиск,
`contextualize.py` можно пропустить, он этот файл перезапишет. Подробности в `RUNBOOK.md`.
