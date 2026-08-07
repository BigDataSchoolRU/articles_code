# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, litellm 1.60.2, OpenRouter API
# LiteLLM как self-hosted слой: тем же ключом ходит в OpenRouter через префикс openrouter/.
import litellm

# Модель с префиксом openrouter/ говорит LiteLLM идти в OpenRouter.
# Ключ берётся из переменной окружения OPENROUTER_API_KEY автоматически.
r = litellm.completion(
    model="openrouter/openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
    max_tokens=10,
)

# Ответ в том же формате OpenAI, что и у прямого вызова OpenRouter.
print("litellm -> OpenRouter:", r.choices[0].message.content)
print("model:", r.model)
