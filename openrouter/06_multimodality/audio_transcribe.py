# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Транскрипция: тот же ключ, эндпоинт /audio/transcriptions, файл speech.wav из speech_synthesize.py.
import os
import httpx

# Ключ из окружения.
key = os.environ["OPENROUTER_API_KEY"]

# Аудио отправляем как multipart-файл, модель распознавания указываем в data.
r = httpx.post(
    "https://openrouter.ai/api/v1/audio/transcriptions",
    headers={"Authorization": f"Bearer {key}"},
    timeout=120,
    files={"file": ("speech.wav", open("speech.wav", "rb"), "audio/wav")},
    data={"model": "openai/gpt-4o-transcribe"},
).json()

# В ответе поле text содержит распознанную речь.
print("транскрипция:", r["text"])
