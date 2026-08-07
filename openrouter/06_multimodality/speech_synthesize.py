# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Синтез речи: аудио-выход идёт стримом (PCM16), собираем WAV.
import os
import base64
import json
import wave
import httpx

# Ключ из окружения.
key = os.environ["OPENROUTER_API_KEY"]

# Буфер под сырые PCM16-семплы, которые придут кусками в стриме.
pcm = bytearray()

# Аудио-выход требует stream=True. Читаем поток SSE построчно.
with httpx.stream(
    "POST",
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    timeout=180,
    json={
        "model": "openai/gpt-audio",
        "modalities": ["text", "audio"],
        "audio": {"voice": "alloy", "format": "pcm16"},  # голос и сырой формат аудио
        "stream": True,
        "messages": [{"role": "user", "content": "Скажи ровно фразу: Мультимодальность через один ключ"}],
    },
) as r:
    for line in r.iter_lines():
        # Интересуют только строки с данными события.
        if not line.startswith("data: "):
            continue
        chunk = line[6:]
        if chunk.strip() == "[DONE]":
            break
        # Аудио-байты лежат в delta.audio.data как base64, накапливаем их.
        au = json.loads(chunk)["choices"][0]["delta"].get("audio")
        if au and au.get("data"):
            pcm += base64.b64decode(au["data"])

# Оборачиваем сырой PCM16 в WAV: моно, 16 бит, 24 кГц.
with wave.open("speech.wav", "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(24000)
    w.writeframes(bytes(pcm))

print(f"речь сохранена: speech.wav, {len(pcm)} байт PCM16")
