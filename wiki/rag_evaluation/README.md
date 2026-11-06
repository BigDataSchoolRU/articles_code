# RAG evaluation

Код к статье [RAG evaluation](https://bigdataschool.ru/wiki/rag_evaluation/).

Два демо показывают, как RAG-систему оценивают по звеньям. Небольшая база знаний про Apache
Kafka (12 фрагментов) и пять вопросов с эталонным ответом и разметкой релевантных фрагментов.
На одном индексе работают два retriever'а: нормальный отдаёт три ближайших фрагмента, испорченный
только один. Первое демо считает метрики поиска без LLM, по разметке. Второе генерирует ответы
локальной моделью и считает в Ragas метрики Faithfulness и Context Recall, а судьёй выступает
та же модель в Ollama.

## Состав

| Файл | Что внутри |
|---|---|
| `corpus.jsonl` | база знаний: 12 коротких фрагментов про Kafka с id `k01`-`k12` |
| `dataset.jsonl` | 5 вопросов: текст, эталонный ответ, id релевантных фрагментов |
| `retrieval_metrics.py` | поиск по эмбеддингам `nomic-embed-text`, hit rate@k, recall@k, MRR и nDCG@k для top-3 и top-1, без LLM |
| `ragas_eval.py` | ответ `qwen2.5:7b` по найденному контексту, затем Faithfulness и Context Recall из Ragas Collections API с судьёй через `llm_factory` |
| `requirements.txt` | версии пакетов, на которых снят вывод |
| `docker-compose.yml` | Ollama в Docker, если она не установлена локально |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором типовых граблей |

## Окружение

Python 3.12, Ragas 0.4.3, `langchain-community` 0.3.31 (пин обязателен, см. RUNBOOK), openai
1.109.1. Ollama 0.40.13, генератор и судья `qwen2.5:7b` (4.7 ГБ), эмбеддинги `nomic-embed-text`
(274 МБ, 768 измерений). Прогнано на Ubuntu 24.04 x86_64, 4 vCPU без GPU, Ollama в Docker.
Первое демо идёт секунды, второе на CPU занимает десятки минут: каждая метрика Ragas это
несколько вызовов модели-судьи.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
.venv/bin/python retrieval_metrics.py
.venv/bin/python ragas_eval.py qwen2.5:7b
```

Скрипты обращаются к Ollama по адресу `http://localhost:11434` и читают `corpus.jsonl` и
`dataset.jsonl` из текущего каталога, поэтому запускать их нужно из этой папки. Подробности по
шагам, ожидаемый вывод и что делать, если пошло не так, в [RUNBOOK.md](RUNBOOK.md).
