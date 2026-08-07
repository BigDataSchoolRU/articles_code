# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Свой порядок провайдеров и запрет фолбэка: только заданные провайдеры, без подмены.
import os
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

MODEL = "meta-llama/llama-3.3-70b-instruct"

# order задаёт порядок провайдеров, allow_fallbacks=False запрещает подмену чужим.
resp = client.chat.completions.create(
    model=MODEL,
    messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
    max_tokens=20,
    extra_body={"provider": {"order": ["Together", "DeepInfra"], "allow_fallbacks": False}},
)

# Ожидаем Together как первого в списке.
print("provider:", resp.provider)
