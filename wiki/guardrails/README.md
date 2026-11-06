# Guardrails

Код к статье [Guardrails](https://bigdataschool.ru/wiki/guardrails/).

Два демо показывают guardrails как программируемые проверки вокруг вызова модели, а не
свойство её весов. Первое собирает входной и выходной слой руками на стандартной библиотеке
Python и HTTP API Ollama: правило на регулярных выражениях, классификатор безопасности
`llama-guard3:1b` и LLM-проверку своей политики. На семи запросах видно, какой слой что ловит,
сколько стоит каждая проверка, где политика обходится перефразированием и где правило даёт
ложное срабатывание. Второе показывает тот же механизм в OpenAI Agents SDK: входной guardrail
с tripwire в блокирующем и параллельном режиме и отмену вызова модели.

## Состав

| Файл | Что внутри |
|---|---|
| `01_rails_pipeline.py` | входной слой из трёх ступеней (правило PII, `llama-guard3:1b`, политика на `qwen2.5:7b`), вызов модели, выходной слой (правило PII и тот же классификатор на ответе); задержка каждого слоя и сводная таблица |
| `02_agents_sdk_tripwire.py` | агент OpenAI Agents SDK на Ollama через OpenAI-совместимый `/v1`, `@input_guardrail` с `run_in_parallel=False` и `True`, перехват `InputGuardrailTripwireTriggered`, хронология вызова модели |
| `requirements.txt` | версии пакетов, на которых снят вывод (нужны только для `02`) |
| `docker-compose.yml` | Ollama в Docker, если она не установлена локально |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором типовых граблей |

## Окружение

Python 3.12, `openai-agents` 0.24.0, `openai` 3.46.0. Ollama 0.40.13, основная модель
`qwen2.5:7b` (4.7 ГБ), классификатор `llama-guard3:1b` (1.6 ГБ). Прогнано на Ubuntu 24.04
x86_64, 4 vCPU без GPU, Ollama в Docker. Оба демо вместе идут около трёх минут: ответы
модели обрезаны до 60 токенов.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama pull qwen2.5:7b
ollama pull llama-guard3:1b
.venv/bin/python 01_rails_pipeline.py qwen2.5:7b
.venv/bin/python 02_agents_sdk_tripwire.py qwen2.5:7b
```

Адрес Ollama скрипты берут из `OLLAMA_URL`, по умолчанию `http://localhost:11434`.
Подробности по шагам, ожидаемый вывод и что делать, если пошло не так, в [RUNBOOK.md](RUNBOOK.md).
