# Hybrid Search (гибридный поиск)

Код к статье https://bigdataschool.ru/wiki/hybrid_search/

Демо fusion-слоя гибридного поиска: лексический поиск (BM25) и векторный поиск
(эмбеддинги) по одному корпусу дают разные ранжированные списки, слияние — своя
реализация Reciprocal Rank Fusion (RRF) по формуле `1/(k+rank)`.

## Состав

| Файл | Что делает |
|---|---|
| `bm25_vs_vector.py` | один запрос, два независимых поисковика (BM25 и векторный) на одном корпусе — показывает, где и почему расходится их топ-5 |
| `rrf_fusion.py` | те же два ретривера плюс RRF-слияние их топ-5 в один ранжированный список с разбором вклада каждого источника |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором граблей |

## Окружение

macOS 26.5.2 (arm64), Python 3.12.13, Ollama 0.32.13, модель `nomic-embed-text`,
python-клиент `ollama` 0.6.2, `rank-bm25` 0.2.2, `numpy` 2.5.2.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
ollama pull nomic-embed-text
./.venv/bin/python3 bm25_vs_vector.py
./.venv/bin/python3 rrf_fusion.py
```

Подробности по каждому шагу и что должно быть в выводе — в `RUNBOOK.md`.
