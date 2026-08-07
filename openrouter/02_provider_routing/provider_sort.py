# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, openai 2.53.0, OpenRouter API
# Сортировка провайдеров одной модели по цене и по пропускной способности.
import os
from openai import OpenAI

# Клиент на base_url OpenRouter, ключ из окружения.
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

MODEL = "meta-llama/llama-3.3-70b-instruct"  # у модели много провайдеров

# Один и тот же запрос, меняется только критерий выбора провайдера.
for sort_by in ("price", "throughput"):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
        max_tokens=20,
        # Настройки провайдера идут в extra_body поверх стандартного API OpenAI.
        extra_body={"provider": {"sort": sort_by}},
    )
    # resp.provider показывает, кто реально обслужил запрос.
    print(f"sort={sort_by:<11} provider={resp.provider}")
