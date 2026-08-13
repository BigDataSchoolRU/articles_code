# RUNBOOK: два агента, которые общаются по A2A

Пошаговый прогон демо к статье «A2A (Agent2Agent Protocol)». Оба агента поднимаются локально,
внешние API и ключи не нужны: работу выполняет модель в Ollama на вашей машине.

## Окружение

| Компонент | Версия при прогоне |
|---|---|
| macOS | 26.5.2 (arm64) |
| Протокол A2A | 1.0 |
| a2a-sdk | 1.1.2 |
| Python | 3.12.13 |
| Ollama (сервер) | 0.32.9 |
| ollama (python-клиент) | 0.6.2 |
| Модель | qwen2.5:7b |

Должно быть доступно: Ollama на `http://localhost:11434` со скачанной чат-моделью и свободный
порт 41241. Другой адрес Ollama подставляется переменной `OLLAMA_HOST`, другой порт агента
правится в константах `HOST` и `PORT` файла `course_agent.py`.

## Шаг 1. Проверить Ollama и модель

```bash
ollama --version
curl -s -m 5 http://localhost:11434/api/tags | head -c 200
ollama list
```

В выводе должна быть версия сервера, JSON со списком моделей и таблица с `qwen2.5:7b`. Если
модели нет, скачайте её:

```bash
ollama pull qwen2.5:7b
```

Шаг прошёл, если `ollama list` показывает модель и её размер.

## Шаг 2. Поставить зависимости

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install --upgrade pip
./.venv/bin/python3 -m pip install "a2a-sdk[http-server]" uvicorn ollama
./.venv/bin/python3 -m pip show a2a-sdk | grep -E "^(Name|Version)"
```

Шаг прошёл, если `pip show` печатает `a2a-sdk` версии 1.1.2 или новее. Экстра `http-server`
тянет Starlette и sse-starlette: без неё серверные маршруты не соберутся.

## Шаг 3. Поднять удалённого агента

```bash
./.venv/bin/python3 course_agent.py
```

Терминал занят процессом и молчит: логи уровня `warning`. Проверка в соседнем терминале:

```bash
curl -s http://127.0.0.1:41241/.well-known/agent-card.json | python3 -m json.tool --no-ensure-ascii
```

Шаг прошёл, если пришёл JSON с полями `name`, `supportedInterfaces`, `capabilities` и `skills`.
В `supportedInterfaces` должен стоять `"protocolVersion": "1.0"`.

## Шаг 4. Вызвать агента голым JSON-RPC

Полезно, чтобы увидеть формат протокола без обёрток SDK.

```bash
curl -s -X POST http://127.0.0.1:41241/a2a/jsonrpc/ \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{"jsonrpc":"2.0","id":"req-1","method":"SendMessage","params":{"message":{"role":"ROLE_USER","messageId":"msg-1","parts":[{"text":"Сколько длится курс MLOPS?"}]}}}' \
  | python3 -m json.tool --no-ensure-ascii
```

Шаг прошёл, если в ответе есть объект `task` со статусом `TASK_STATE_COMPLETED` и массив
`artifacts`, внутри которого лежит ответ модели. Первый вызов после старта Ollama может
занять до минуты: модель грузится в память.

## Шаг 5. Запустить клиентского агента

```bash
./.venv/bin/python3 client_agent.py
```

Шаг прошёл, если вывод содержит блок Agent Card со списком навыков, затем поток событий
`TASK_STATE_SUBMITTED` -> `TASK_STATE_WORKING` -> `artifact_update` -> `TASK_STATE_COMPLETED`,
и в конце текст ответа удалённого агента.

## Если не так

- **`A2A version '0.3' is not supported by this handler`**, код ошибки -32009. Клиент не сообщил
  версию протокола, а карточка агента объявлена как 0.3. Проверьте, что в `AgentInterface`
  стоит `protocol_version="1.0"`, а в ручном запросе curl есть заголовок `A2A-Version: 1.0`.
- **`A2AClientTimeoutError: Client Request timed out`.** Клиент по умолчанию ждёт ответ
  недолго, а локальная модель отвечает секунды и десятки секунд. Передайте свой httpx-клиент
  с увеличенным таймаутом через `ClientConfig(httpx_client=...)`, как в `client_agent.py`.
- **`InvalidAgentResponseError`.** Исполнитель нарушил правила потока событий: объект `Task`
  обязан уйти в очередь первым, смешивать `Message` с событиями задачи в одном потоке нельзя.
- **`Connection refused` на порт 41241.** Агент не поднялся или порт занят. Проверьте вывод
  терминала со шагом 3 и при необходимости смените порт в `course_agent.py`.
- **Пустой или странный ответ модели.** Проверьте, что модель скачана целиком, и повторите
  запрос: демо намеренно ставит `temperature 0.1`, но локальные модели всё равно плавают.
