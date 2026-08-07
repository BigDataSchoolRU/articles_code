# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Кэш промптов: второй вызов с тем же контекстом читает кэш и стоит дешевле.
import os
import httpx

# Ключ из окружения.
key = os.environ["OPENROUTER_API_KEY"]

# Большой общий контекст, который дорого гонять целиком на каждом запросе.
context = "Справочный контекст для кэша. " * 900

def ask():
    payload = {
        "model": "anthropic/claude-haiku-4.5",
        "messages": [
            # cache_control помечает блок для кэширования у провайдера.
            {"role": "system", "content": [
                {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}}
            ]},
            {"role": "user", "content": "Ответь одним словом: ок"},
        ],
        "max_tokens": 5,
        "session_id": "cache-demo-1",  # пиннит провайдера, чтобы кэш был тёплым
        "usage": {"include": True},    # просим вернуть usage с деталями кэша
    }
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    u = r.json()["usage"]
    # cached_tokens показывает, сколько токенов прочитано из кэша.
    cached = u["prompt_tokens_details"]["cached_tokens"]
    return u["prompt_tokens"], cached, u["cost"]

# Первый вызов пишет кэш, второй его читает и стоит дешевле.
for i in (1, 2):
    prompt_tokens, cached, cost = ask()
    print(f"вызов {i}: prompt={prompt_tokens} cached={cached} cost=${cost:.6f}")
