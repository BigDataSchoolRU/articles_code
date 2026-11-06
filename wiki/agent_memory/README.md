# Agent memory

Код к статье [Agent memory](https://bigdataschool.ru/wiki/agent_memory/).

Три демо на LangGraph и локальной модели в Ollama показывают два уровня памяти LLM-агента.
Кратковременная живёт в состоянии треда: checkpointer сохраняет историю сообщений по
`thread_id` и подаёт её в окно модели на следующем шаге. Долговременная живёт в отдельном
хранилище Store: факты о пользователе лежат в пространстве имён `("memories", user_id)`,
ищутся по смыслу через эмбеддинги и доступны агенту в любой новой сессии. Третье демо про то,
что с памятью делать дальше: обновлять, удалять и ограничивать сроком жизни.

## Состав

| Файл | Что внутри |
|---|---|
| `01_short_term.py` | граф с одним узлом модели и `SqliteSaver`: факт из первой реплики доступен в том же треде, переживает перезапуск процесса и не виден в другом треде; рост окна по `prompt_eval_count` |
| `02_long_term.py` | цикл памяти recall → call_model → write_memory поверх `SqliteStore` с семантическим индексом: факты из первой сессии находятся во второй, другой пользователь их не видит |
| `03_forget.py` | противоречивые факты при дозаписи (append) против обновления по ключу (upsert), `delete` и TTL с `sweep_ttl()` |
| `requirements.txt` | версии пакетов, на которых снят вывод |
| `docker-compose.yml` | Ollama в Docker, если она не установлена локально |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором типовых граблей |

## Окружение

Python 3.12, LangGraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-ollama 1.1.0.
Ollama 0.40.13, модель агента `qwen2.5:7b` (4.7 ГБ), модель эмбеддингов `nomic-embed-text`
(274 МБ, 768 измерений). Прогнано на Ubuntu 24.04 x86_64, 4 vCPU без GPU, Ollama в Docker.
Все три демо вместе идут несколько минут: ответы короткие, диалоги в одну-три реплики.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
.venv/bin/python 01_short_term.py qwen2.5:7b
.venv/bin/python 02_long_term.py qwen2.5:7b
.venv/bin/python 03_forget.py qwen2.5:7b
```

Адрес Ollama скрипты берут из `OLLAMA_URL`, по умолчанию `http://localhost:11434`. Каждый
скрипт создаёт рядом с собой свой файл SQLite и удаляет его при следующем запуске, поэтому
прогон повторяем. Подробности по шагам, ожидаемый вывод и что делать, если пошло не так, в
[RUNBOOK.md](RUNBOOK.md).
