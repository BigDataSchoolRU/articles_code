# RUNBOOK. OpenRouter в n8n без кода

## Окружение
Часть 1: проверка Python-сценария на четыре модальности одним ключом, стенд EU-нода (AWS Stockholm), Python 3.12.3, httpx 0.28.1. Часть 2: развёртывание self-hosted n8n на своём сервере и импорт готового флоу. Файлы: `multimodal_onekey.py`, `openrouter_n8n_content_flow.json`.

## Шаг 1. Один ключ на текст, картинку, речь и транскрипцию (multimodal_onekey.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os, base64, json, wave
import httpx

key = os.environ["OPENROUTER_API_KEY"]
H = {"Authorization": f"Bearer {key}"}
BASE = "https://openrouter.ai/api/v1"

# 1. Текст
chat = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=60, json={
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "Ответь одним словом: готово"}],
    "max_tokens": 5,
}).json()
print("текст:", chat["choices"][0]["message"]["content"].strip())

# 2. Картинка (chat + modalities), сохраняем PNG
img = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=120, json={
    "model": "google/gemini-2.5-flash-image",
    "messages": [{"role": "user", "content": "Нарисуй простой логотип: синий круг на белом фоне"}],
    "modalities": ["image", "text"],
}).json()
url = img["choices"][0]["message"]["images"][0]["image_url"]["url"]
png = base64.b64decode(url.split(",", 1)[1])
open("logo.png", "wb").write(png)
print("картинка: logo.png,", len(png), "байт")

# 3. Синтез речи (стрим PCM16), собираем WAV
pcm = bytearray()
with httpx.stream("POST", f"{BASE}/chat/completions", headers=H, timeout=180, json={
    "model": "openai/gpt-audio",
    "modalities": ["text", "audio"],
    "audio": {"voice": "alloy", "format": "pcm16"},
    "stream": True,
    "messages": [{"role": "user", "content": "Скажи ровно фразу: Проверка транскрипции через ОупенРоутер"}],
}) as r:
    for line in r.iter_lines():
        if not line.startswith("data: "):
            continue
        chunk = line[6:]
        if chunk.strip() == "[DONE]":
            break
        au = json.loads(chunk)["choices"][0]["delta"].get("audio")
        if au and au.get("data"):
            pcm += base64.b64decode(au["data"])
with wave.open("speech.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(bytes(pcm))
print("речь: speech.wav,", len(pcm), "байт PCM16")

# 4. Транскрипция того же аудио
tr = httpx.post(f"{BASE}/audio/transcriptions", headers=H, timeout=120,
                files={"file": ("speech.wav", open("speech.wav", "rb"), "audio/wav")},
                data={"model": "openai/gpt-4o-transcribe"}).json()
print("транскрипция:", tr["text"])
```

Команда: `python3 multimodal_onekey.py`

Ожидаемый вывод (реальный прогон):

```
текст: Сделано.
картинка: logo.png, 169274 байт
речь: speech.wav, 153600 байт PCM16
транскрипция: Проверка транскрипции через openrouter.
```

Шаг пройден, если все четыре строки напечатались без ошибок и появились файлы `logo.png` и `speech.wav`. Текст ответа и точный размер файлов может отличаться от прогона к прогону.

## Шаг 2. Создать ВМ для n8n

Поднять сервер (2 vCPU, 2 ГБ памяти, 20 ГБ SSD достаточно для старта), Ubuntu 24.04 LTS, публичный IPv4, доступ по SSH-ключу.

Проверка: сервер доступен по SSH, публичный IP присвоен.

## Шаг 3. Открыть порт 5678

Добавить входящее правило на 5678 (интерфейс n8n) в настройках сети/файрвола. Порт 22 для SSH оставить только для своего IP.

Проверка: `nc -zv <публичный_IP> 5678` отдаёт `succeeded`, если контейнер уже поднят, иначе `connection refused` до шага 4.

## Шаг 4. Поставить Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
docker run --rm hello-world
```

Проверка: `hello-world` печатает `Hello from Docker!` без ошибок.

## Шаг 5. Запустить n8n

```bash
docker run -d --name n8n --restart unless-stopped \
  -p 5678:5678 \
  -v n8n_data:/home/node/.n8n \
  -e N8N_HOST=<публичный_IP_или_домен> \
  -e N8N_PORT=5678 \
  -e N8N_PROTOCOL=http \
  -e GENERIC_TIMEZONE=Europe/Moscow \
  -e N8N_SECURE_COOKIE=false \
  docker.n8n.io/n8nio/n8n
```

Проверка: `docker ps` показывает контейнер `n8n` со статусом `Up`. В браузере `http://<публичный_IP>:5678` открывает экран создания администратора.

## Шаг 6. Импортировать флоу и подключить OpenRouter

1. Import from File, загрузить `openrouter_n8n_content_flow.json`.
2. Появляется флоу из трёх узлов: Запуск вручную, Тема, OpenRouter.
3. В узле OpenRouter (HTTP Request) задать ключ через Authentication, Generic Credential, Header Auth: имя `Authorization`, значение `Bearer sk-or-...`.
4. Нажать Test workflow.

Ожидаемый результат выполнения флоу: узел Тема отдаёт строку `OpenRouter в n8n без кода`, узел OpenRouter возвращает готовый пост в блог по этой теме.

Проверка: у узла OpenRouter в панели выполнения зелёная галка, в выводе есть поле с текстом от модели, а не ошибка HTTP.

## Что делать если не так

- `multimodal_onekey.py` падает на шаге аудио: увеличьте `timeout`, синтез речи может занимать больше времени, чем чат-запрос.
- Интерфейс n8n не открывается: проверьте, что порт 5678 открыт в настройках сети и `docker ps` показывает контейнер живым.
- Ошибка 403 от OpenRouter внутри n8n: гео-блокировка Cloudflare на российский IP. Нужен прокси, зарубежный egress либо сервер в другом регионе.
- Ошибка 401 от OpenRouter внутри n8n: ключ не подставился или указан с опечаткой, проверьте заголовок Authorization в креде узла.
- Флоу не сохранился после перезапуска контейнера: контейнер запущен без тома `-v n8n_data:/home/node/.n8n`, пересоздайте с этим флагом.
