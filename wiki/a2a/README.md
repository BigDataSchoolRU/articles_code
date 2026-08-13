# A2A (Agent2Agent Protocol)

Код к Wiki-статье «A2A (Agent2Agent Protocol)» на сайте BigDataSchool: https://bigdataschool.ru/wiki/a2a/

## Состав

- `course_agent.py` — удалённый агент A2A: публикует Agent Card, обслуживает JSON-RPC биндинг,
  отвечает на вопросы по каталогу курсов через локальную модель в Ollama
- `client_agent.py` — клиентский агент: скачивает Agent Card, собирает клиента по ней и
  делегирует задачу удалённому агенту
- `RUNBOOK.md` — пошаговый прогон с проверками

## Окружение

| Компонент | Версия при прогоне |
|---|---|
| Протокол A2A | 1.0 |
| a2a-sdk (Python) | 1.1.2 |
| Python | 3.12.13 |
| Ollama (сервер) | 0.32.9 |
| ollama (python-клиент) | 0.6.2 |
| Модель | qwen2.5:7b |

Должно быть доступно: запущенный сервер Ollama на `http://localhost:11434` со скачанной моделью
с поддержкой чата и свободный порт 41241.

## Как запустить

1. Поставить зависимости: `pip install "a2a-sdk[http-server]" uvicorn ollama`
2. В одном терминале поднять удалённого агента: `python3 course_agent.py`
3. В другом запустить клиентского агента: `python3 client_agent.py`

Подробности и проверки после каждого шага в `RUNBOOK.md`.
