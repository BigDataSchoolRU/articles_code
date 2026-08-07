# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Видео: асинхронный поток. Отправляем задание, поллим статус, забираем ссылку на результат.
# ВНИМАНИЕ: генерация видео платная, один клип стоит реальные деньги (в прогоне wan-2.7 вышло $0.5).
import os
import time
import httpx

key = os.environ["OPENROUTER_API_KEY"]
H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

# 1. Отправляем задание, сразу получаем job id и статус pending.
job = httpx.post(
    "https://openrouter.ai/api/v1/videos",
    headers=H,
    timeout=30,
    json={"model": "alibaba/wan-2.7", "prompt": "a calm blue circle on white background, 2 seconds"},
).json()
jid = job["id"]
print("submit:", job["status"], "| id:", jid)

# 2. Поллим статус, пока задание не завершится.
while True:
    st = httpx.get(f"https://openrouter.ai/api/v1/videos/{jid}", headers={"Authorization": f"Bearer {key}"}, timeout=30).json()
    print("status:", st["status"])
    if st["status"] not in ("pending", "processing", "queued", "running"):
        break
    time.sleep(15)

# 3. Забираем ссылку на готовое видео и стоимость.
print("ссылка на видео:", st["unsigned_urls"][0])
print(f"стоимость: ${st['usage']['cost']}")
