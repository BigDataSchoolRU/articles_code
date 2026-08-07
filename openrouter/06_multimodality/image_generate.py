# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Генерация картинки: chat с modalities возвращает изображение прямо в ответе.
import os
import base64
import httpx

# Ключ из окружения.
key = os.environ["OPENROUTER_API_KEY"]

# Обычный chat-запрос, но с modalities ["image","text"]: просим модель отдать картинку.
r = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    timeout=120,
    json={
        "model": "google/gemini-2.5-flash-image",  # модель с картинками на выход
        "messages": [{"role": "user", "content": "Нарисуй простой логотип: синий круг на белом фоне"}],
        "modalities": ["image", "text"],
    },
).json()

# Картинка приходит в message.images как data-URL с base64 внутри.
url = r["choices"][0]["message"]["images"][0]["image_url"]["url"]
png = base64.b64decode(url.split(",", 1)[1])  # отрезаем префикс data:image/png;base64,

# Сохраняем в файл.
with open("logo.png", "wb") as f:
    f.write(png)

print(f"картинка сохранена: logo.png, {len(png)} байт, cost=${r['usage']['cost']:.6f}")
