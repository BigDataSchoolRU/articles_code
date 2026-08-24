# ChromaDB

Код к статье [ChromaDB](https://bigdataschool.ru/wiki/chromadb/) в Wiki Школы Больших Данных.

## Состав

| Файл | Что делает |
|---|---|
| `basic_collection.py` | создаёт постоянную коллекцию, вставляет 12 документов с метаданными, замеряет вставку и смысловой поиск |
| `filters_and_search.py` | фильтры по метаданным, полнотекстовый `$contains`, регулярное выражение `$regex` и их сочетание с векторным поиском |
| `requirements.txt` | пины зависимостей, снятые с рабочего стенда |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Python 3.12, chromadb 1.5.9, Ollama 0.32.13 с моделью `nomic-embed-text`. Внешние API и ключи
не нужны, всё считается локально.

## Запуск

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install -r requirements.txt
ollama pull nomic-embed-text
./.venv/bin/python3 basic_collection.py
./.venv/bin/python3 filters_and_search.py
```

Подробности, ожидаемый вывод и разбор ошибок в [RUNBOOK.md](RUNBOOK.md).
