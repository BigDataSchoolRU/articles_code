# ReAct

Код к Wiki-статье «ReAct» на сайте BigDataSchool: https://bigdataschool.ru/wiki/react/

## Состав

- `react_agent_demo.py` — цикл ReAct (Thought → Action → Observation) на текущем API `create_agent` из `langchain.agents`, с инструментом сравнения длины слов и локальной моделью qwen2.5:7b
- `create_react_agent_deprecation_check.py` — фиксирует дословный текст предупреждения об устаревании `create_react_agent` в LangGraph 1.2.11
- `RUNBOOK.md` — пошаговый прогон с проверками

## Окружение

- Python 3.12.13
- langchain 1.3.15, langchain-core 1.5.4, langgraph 1.2.11, langchain-ollama 1.1.0
- Ollama 0.32.13 на `http://localhost:11434`, модель qwen2.5:7b

Внешние ключи и платные API не нужны, всё считается локально.

## Как запустить

1. Поднять Ollama и скачать модель: `ollama pull qwen2.5:7b`
2. Поставить зависимости: `pip install "langchain==1.3.15" "langgraph==1.2.11" "langchain-ollama==1.1.0"`
3. Прогнать цикл ReAct: `python3 react_agent_demo.py`
4. Проверить факт устаревания `create_react_agent`: `python3 create_react_agent_deprecation_check.py`
