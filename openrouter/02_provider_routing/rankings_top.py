# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Топ моделей по объёму токенов за день через датасет-эндпоинт rankings-daily.
import os
import httpx

# Ключ из окружения, дата, за которую берём рейтинг.
key = os.environ["OPENROUTER_API_KEY"]
day = "2026-08-03"

# Датасет-эндпоинт отдаёт топ моделей по токенам за указанный день.
r = httpx.get(
    "https://openrouter.ai/api/v1/datasets/rankings-daily",
    params={"start_date": day, "end_date": day},
    headers={"Authorization": f"Bearer {key}"},
    timeout=30,
)
r.raise_for_status()

rows = r.json()["data"]
# Служебную строку other отбрасываем, берём топ-10 моделей.
rows = [x for x in rows if x["model_permaslug"] != "other"][:10]

# Печатаем номер, слаг модели и объём в миллиардах токенов.
print(f"Топ-10 моделей OpenRouter за {day} по токенам:")
for i, x in enumerate(rows, 1):
    tokens = int(x["total_tokens"])
    print(f"{i:>2}. {x['model_permaslug']:<45} {tokens/1e9:>8.1f}B")
