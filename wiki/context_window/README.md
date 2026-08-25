# Контекстное окно (Context Window)

Код к статье https://bigdataschool.ru/wiki/context_window/

Три демо про то, чем на самом деле ограничен один вызов языковой модели: бюджет считается в
токенах, всё лишнее отрезается молча, а длинный вход оплачивается на каждом ходу.

## Состав

| Файл | Что делает |
|---|---|
| `01_tokens_vs_chars.py` | считает один и тот же текст в символах и токенах, сравнивает русский с английским |
| `02_needle_overflow.py` | кладёт факт в начало длинного промпта и показывает, при каком `num_ctx` он теряется |
| `03_prefill_cost.py` | меряет время префилла на растущей длине входа |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором граблей |

## Окружение

macOS 26.5.2 (arm64), Python 3.12.13, Ollama 0.32.13, модель `qwen2.5:7b`, tiktoken 0.13.0,
python-клиент `ollama` 0.6.2.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install tiktoken ollama
ollama pull qwen2.5:7b
./.venv/bin/python3 01_tokens_vs_chars.py
./.venv/bin/python3 02_needle_overflow.py
./.venv/bin/python3 03_prefill_cost.py
```

Подробности по каждому шагу и что должно быть в выводе — в `RUNBOOK.md`.
