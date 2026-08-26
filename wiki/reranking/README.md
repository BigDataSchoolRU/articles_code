# Reranking (переранжирование результатов поиска)

Код к статье [Reranking](https://bigdataschool.ru/wiki/reranking/).

Двухэтапный retrieval на одном запросе и корпусе из 10 документов про Kafka и смежные big data
системы: baseline-поиск по косинусному сходству эмбеддингов (`nomic-embed-text` через Ollama),
затем переранжирование top-5 кандидатов cross-encoder'ом (`cross-encoder/ms-marco-MiniLM-L-6-v2`
через `sentence-transformers`). Всё считается локально на CPU, GPU не нужен.

## Состав

| Файл | Что внутри |
|---|---|
| `corpus.py` | демо-корпус из 10 документов и тестовый запрос |
| `retrieve.py` | эмбеддинги через Ollama, косинусное сходство, baseline top-N |
| `rerank.py` | переранжирование top-N кандидатов через `CrossEncoder` |
| `demo.py` | связывает baseline и reranking, печатает оба порядка выдачи |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором типовых граблей |

## Окружение

macOS 26.5.2 (arm64), Ollama 0.32.13 с моделью `nomic-embed-text`, python-пакеты `ollama` 0.6.2,
`sentence-transformers` 6.0.0, `torch` 2.13.0. Модель reranker'а (~90 МБ) скачивается
автоматически из Hugging Face Hub при первом запуске.

## Как запустить

```bash
ollama pull nomic-embed-text
pip install ollama sentence-transformers
python3 demo.py
```

Подробности по шагам, ожидаемый вывод и что делать, если пошло не так, — в
[RUNBOOK.md](RUNBOOK.md).

## Что получилось на прогоне

Baseline по эмбеддингам ставит документ с точным ответом на вопрос (`kafka_exactly_once`) только
на 4-е место из 5 — выше него косинусное сходство поднимает документы, которые просто упоминают
Kafka в общем контексте (`kafka_consumer_group`, `kafka_connect`, `kafka_overview`). После
reranking cross-encoder'ом `kafka_exactly_once` поднимается на 1-е место, а остальные четыре
сохраняют относительный порядок.

Скор cross-encoder'а — сырой логит модели MS MARCO, не нормализован в 0-1: важен порядок значений,
а не сама величина.

Неудобный результат отдельно: конструктор `CrossEncoder(...)` даже с уже закэшированными весами
инициализируется около 7 секунд при первом обращении за процесс, тогда как сам `predict()` на
5 парах после этого укладывается в 0.01-0.4 с. На проде это означает прогрев reranker'а заранее,
а не на первом реальном запросе.
