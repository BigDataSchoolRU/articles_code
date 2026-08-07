# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Response Healing: OpenRouter чинит битый JSON до того, как он долетит до приложения.
import os, json
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

# Плагин включается одной строкой в plugins. Он правит синтаксис JSON, а не схему.
resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Верни JSON объект с полями name и ok"}],
    response_format={"type": "json_object"},
    extra_body={"plugins": [{"id": "response-healing"}]},
)

raw = resp.choices[0].message.content
print("ответ:", raw)

# Даже если модель уронит запятую или скобку, плагин починит это до нас.
data = json.loads(raw)
print("распарсено без ошибок, ключи:", list(data.keys()))
