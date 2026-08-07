# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Один ключ на всё: текст, картинка, синтез речи и транскрипция через один base_url.
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
