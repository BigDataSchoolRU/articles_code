# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Субагент: флагман сбрасывает рутину на дешёвого воркера по ходу генерации.
import os
import httpx

# Ключ из окружения, оркестратор дорогой, воркер дешёвый.
key = os.environ["OPENROUTER_API_KEY"]
ORCH = "openai/gpt-4o"
WORKER = "openai/gpt-4o-mini"

# Задача с самодостаточной рутиной, которую логично делегировать.
task = (
    "Составь короткий пресс-релиз про запуск нашего API. "
    "Рутинную часть, резюме из трёх буллетов по фактам, делегируй воркеру: "
    "единый ключ, 300+ моделей, оплата криптой. Затем собери финальный абзац сам."
)

payload = {
    "model": ORCH,
    "messages": [{"role": "user", "content": task}],
    "tools": [{
        # Серверный инструмент субагента: воркер, его инструкции и лимит токенов.
        "type": "openrouter:subagent",
        "parameters": {
            "model": WORKER,
            "instructions": "Ты быстрый воркер. Выполни задачу точно и кратко.",
            "max_completion_tokens": 200,
        },
    }],
    "max_tokens": 400,
    "usage": {"include": True},
}

r = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}"},
    json=payload,
    timeout=120,
)
r.raise_for_status()
j = r.json()
u = j["usage"]
# server_tool_use_details говорит, сколько раз реально сработал субагент.
st = u.get("server_tool_use_details", {})

print("делегировано воркеру:", st.get("tool_calls_executed"), "раз")
print(f"общая стоимость запроса: ${u['cost']:.6f}")

# Почему это экономит: сравниваем цену входа оркестратора и воркера из каталога.
models = httpx.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {key}"},
    timeout=60,
).json()["data"]

def price_in(mid):
    # Цена за миллион входных токенов для модели mid.
    return float(next(x for x in models if x["id"] == mid)["pricing"]["prompt"]) * 1e6

po, pw = price_in(ORCH), price_in(WORKER)
print(f"вход $/М: оркестратор {po}, воркер {pw} (воркер дешевле в ~{po / pw:.0f} раз)")
