# Ollama

Код к статье [Ollama](https://bigdataschool.ru/wiki/ollama/).

Демо показывает REST API Ollama через официальный python-клиент: обычный и потоковый chat,
вызов инструмента (tool calling), а также механизм Modelfile — как навесить system-промпт и
параметры на уже скачанный GGUF-вес без переобучения — и метаданные квантования одной модели в
трёх степенях (`q4_0`, `q8_0`, `fp16`).

## Состав

| Файл | Что внутри |
|---|---|
| `chat_tools.py` | `chat()` целиком, `chat(stream=True)` потоком, вызов функции `get_weather` через tool calling с двухшаговым обменом сообщениями |
| `modelfile_quantization.py` | Создание временной модели через `ollama.create()` (аналог `Modelfile`), сравнение `quantization_level` / `parameter_size` / размера на диске у трёх квантований одной модели |
| `RUNBOOK.md` | Пошаговое воспроизведение с ожидаемым выводом на каждом шаге |

## Окружение

Python 3.12, python-клиент `ollama` 0.6.2, сервер Ollama 0.32.13+, модели `qwen2.5:7b` и
`qwen2.5:0.5b-instruct-{q4_0,q8_0,fp16}`.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install ollama

ollama pull qwen2.5:7b
ollama pull qwen2.5:0.5b-instruct-q4_0
ollama pull qwen2.5:0.5b-instruct-q8_0
ollama pull qwen2.5:0.5b-instruct-fp16

./.venv/bin/python3 chat_tools.py
./.venv/bin/python3 modelfile_quantization.py
```

Подробности по каждому шагу, ожидаемый вывод и типовые грабли лежат в `RUNBOOK.md`.
