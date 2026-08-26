# LlamaIndex

Код к Wiki-статье «LlamaIndex» на сайте BigDataSchool: https://bigdataschool.ru/wiki/llamaindex/

## Состав
- `node_chunking_demo.py` - как LlamaIndex режет Document на Node: дефолтные `chunk_size`/`chunk_overlap` SentenceSplitter и разбиение документа уменьшенным чанком
- `basic_rag_pipeline.py` - базовый RAG-пайплайн: индексация корпуса документов, retrieval и генерация ответа через локальные модели Ollama
- `RUNBOOK.md` - пошаговый прогон с проверками

## Окружение
Python 3.12, пакеты `llama-index-core` 0.14.24, `llama-index-llms-ollama` 0.10.1, `llama-index-embeddings-ollama` 0.9.0. Локальная Ollama 0.32.13 на http://localhost:11434 со скачанными моделями `qwen2.5:7b` и `nomic-embed-text`.

## Как запустить
1. `ollama pull qwen2.5:7b && ollama pull nomic-embed-text` (если моделей ещё нет)
2. `python3 -m pip install llama-index-core llama-index-llms-ollama llama-index-embeddings-ollama`
3. `python3 node_chunking_demo.py`
4. `python3 basic_rag_pipeline.py`
