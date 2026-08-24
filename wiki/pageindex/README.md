# PageIndex

Код к Wiki-статье «PageIndex» на сайте BigDataSchool: https://bigdataschool.ru/wiki/pageindex/

## Состав
- `build_tree.py` — строит дерево документа из PDF режимом flash, без обращений к LLM
- `tree_search.py` — reasoning-поиск по дереву на локальной модели через Ollama
- `RUNBOOK.md` — пошаговый прогон с проверками

## Окружение
Python 3.12, pageindex 0.2.10, litellm 1.98.0, pypdfium2 5.12.1, Ollama 0.32.13 с моделью
qwen2.5:7b. PDF-документ кладётся рядом со скриптами под именем `annual_report.pdf`.

## Как запустить
1. `python3 -m venv .venv && ./.venv/bin/python3 -m pip install pageindex litellm pypdfium2`
2. `ollama pull qwen2.5:7b`, сервер поднимается командой `ollama serve`
3. `./.venv/bin/python3 build_tree.py` — дерево уходит в `tree.json`
4. `./.venv/bin/python3 tree_search.py` — ответ на вопрос через выбор узла дерева
