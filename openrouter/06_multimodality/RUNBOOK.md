# RUNBOOK. Мультимодальность: картинки, аудио, видео

## Окружение
Стенд: EU-нода (AWS Stockholm). Python 3.12.3, httpx 0.28.1. Ключ в `OPENROUTER_API_KEY`. Файлы кода: `detect_modalities.py`, `image_generate.py`, `speech_synthesize.py`, `audio_transcribe.py`, `video_generate.py`. Внимание: генерация видео платная, шаг 5 стоит реальные деньги (в прогоне вышло $0.5), запускайте по одному разу и осознанно.

## Шаг 1. Обнаружение возможностей моделей (detect_modalities.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]

models = httpx.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {key}"},
    timeout=60,
).json()["data"]

def out(x, mod):
    return mod in (x.get("architecture", {}).get("output_modalities") or [])

def inp(x, mod):
    return mod in (x.get("architecture", {}).get("input_modalities") or [])

images = [x["id"] for x in models if out(x, "image")]
audio_in = [x["id"] for x in models if inp(x, "audio")]
audio_out = [x["id"] for x in models if out(x, "audio")]

print("картинки на выход:", len(images))
for i in images[:5]:
    print("  ", i)
print("аудио на вход (распознавание и понимание):", len(audio_in))
for i in audio_in[:5]:
    print("  ", i)
print("аудио на выход (синтез речи):", len(audio_out))
for i in audio_out[:5]:
    print("  ", i)
```

Команда: `python3 detect_modalities.py`

Ожидаемый вывод (реальный прогон, счётчики):

```
картинки на выход: 11
аудио на вход: 26
аудио на выход: 4
```

Шаг пройден, если все три счётчика больше нуля. Точные числа растут по мере пополнения каталога моделей, это ожидаемо.

## Шаг 2. Генерация картинки (image_generate.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import base64
import httpx

key = os.environ["OPENROUTER_API_KEY"]

r = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    timeout=120,
    json={
        "model": "google/gemini-2.5-flash-image",
        "messages": [{"role": "user", "content": "Нарисуй простой логотип: синий круг на белом фоне"}],
        "modalities": ["image", "text"],
    },
).json()

url = r["choices"][0]["message"]["images"][0]["image_url"]["url"]
png = base64.b64decode(url.split(",", 1)[1])

with open("logo.png", "wb") as f:
    f.write(png)

print(f"картинка сохранена: logo.png, {len(png)} байт, cost=${r['usage']['cost']:.6f}")
```

Команда: `python3 image_generate.py`

Ожидаемый вывод (реальный прогон): `картинка сохранена: logo.png, 165799 байт, cost=$0.038719`. Шаг пройден, если файл `logo.png` создан, открывается как валидный PNG и `cost` больше нуля.

## Шаг 3. Синтез речи (speech_synthesize.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import base64
import json
import wave
import httpx

key = os.environ["OPENROUTER_API_KEY"]
pcm = bytearray()

with httpx.stream(
    "POST",
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    timeout=180,
    json={
        "model": "openai/gpt-audio",
        "modalities": ["text", "audio"],
        "audio": {"voice": "alloy", "format": "pcm16"},
        "stream": True,
        "messages": [{"role": "user", "content": "Скажи ровно фразу: Мультимодальность через один ключ"}],
    },
) as r:
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
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(24000)
    w.writeframes(bytes(pcm))

print(f"речь сохранена: speech.wav, {len(pcm)} байт PCM16")
```

Команда: `python3 speech_synthesize.py`

Ожидаемый вывод (реальный прогон): `речь сохранена: speech.wav, 148800 байт PCM16`. Шаг пройден, если файл `speech.wav` создан и проигрывается стандартным плеером.

## Шаг 4. Транскрипция (audio_transcribe.py)

Выполняется после шага 3, использует файл `speech.wav`.

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
import os
import httpx

key = os.environ["OPENROUTER_API_KEY"]

r = httpx.post(
    "https://openrouter.ai/api/v1/audio/transcriptions",
    headers={"Authorization": f"Bearer {key}"},
    timeout=120,
    files={"file": ("speech.wav", open("speech.wav", "rb"), "audio/wav")},
    data={"model": "openai/gpt-4o-transcribe"},
).json()

print("транскрипция:", r["text"])
```

Команда: `python3 audio_transcribe.py`

Ожидаемый вывод (реальный прогон): `транскрипция: Мультимодальность через один ключ.`. Шаг пройден, если распознанный текст совпадает по смыслу с фразой, которую озвучили на шаге 3.

## Шаг 5. Генерация видео, платный шаг (video_generate.py)

```python
# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# ВНИМАНИЕ: генерация видео платная, один клип стоит реальные деньги (в прогоне wan-2.7 вышло $0.5).
import os
import time
import httpx

key = os.environ["OPENROUTER_API_KEY"]
H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

job = httpx.post(
    "https://openrouter.ai/api/v1/videos",
    headers=H,
    timeout=30,
    json={"model": "alibaba/wan-2.7", "prompt": "a calm blue circle on white background, 2 seconds"},
).json()
jid = job["id"]
print("submit:", job["status"], "| id:", jid)

while True:
    st = httpx.get(f"https://openrouter.ai/api/v1/videos/{jid}", headers={"Authorization": f"Bearer {key}"}, timeout=30).json()
    print("status:", st["status"])
    if st["status"] not in ("pending", "processing", "queued", "running"):
        break
    time.sleep(15)

print("ссылка на видео:", st["unsigned_urls"][0])
print(f"стоимость: ${st['usage']['cost']}")
```

Команда: `python3 video_generate.py`

Ожидаемый вывод (реальный прогон):

```
submit: pending | id: dih87y7RXNTD47sE4VEp
status: pending
status: completed
ссылка на видео: https://openrouter.ai/api/v1/videos/dih87y7RXNTD47sE4VEp/content?index=0
стоимость: $0.5
```

Шаг пройден, если статус дошёл до `completed` и вернулась ссылка на контент. Перед повторным запуском убедитесь, что осознанно готовы потратить сумму, указанную в прогоне, генерация видео не бесплатна ни у одной модели каталога.

## Что делать если не так

- `detect_modalities.py`: все счётчики нулевые - проверьте, что поле называется именно `architecture.output_modalities` в текущей версии API, формат каталога может обновляться.
- `image_generate.py`: `KeyError` на `images` - модель в этом запросе не вернула картинку, добавьте в промпт более явное указание нарисовать изображение, либо смените модель.
- `speech_synthesize.py`: файл `speech.wav` пустой или очень маленький - стрим прервался раньше, увеличьте `timeout`, аудио генерируется дольше текста.
- `audio_transcribe.py`: пустая транскрипция - проверьте, что `speech.wav` не пустой (шаг 3 должен пройти успешно раньше).
- `video_generate.py`: статус застыл на `processing` дольше нескольких минут - это нормально для видео, генерация может занимать заметное время, не отменяйте задание раньше 5 минут.
