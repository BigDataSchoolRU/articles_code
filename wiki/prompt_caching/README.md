# Prompt Caching (Кэширование промптов)

Код к статье https://bigdataschool.ru/wiki/prompt_caching/

Демо про тот же механизм, что лежит в основе prompt caching у Anthropic и OpenAI:
переиспользование уже посчитанного состояния модели для неизменного префикса запроса —
на локальной модели через Ollama, без облачного API и без биллинга.

## Состав

| Файл | Что делает |
|---|---|
| `cache_prefix_demo.py` | пять вызовов подряд к одной модели: холодный длинный префикс, два продолжения того же диалога, префикс с изменённым символом, повтор оригинального запроса не по порядку — сравнивает `prompt_eval_count` и `prompt_eval_duration` |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором граблей |

## Окружение

macOS 26.5.2 (arm64), Python 3.12.13, Ollama 0.32.13, модель `qwen2.5:7b`, python-клиент
`ollama` 0.6.2.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
ollama pull qwen2.5:7b
./.venv/bin/python3 cache_prefix_demo.py
```

Подробности по каждому шагу и что должно быть в выводе — в `RUNBOOK.md`.
