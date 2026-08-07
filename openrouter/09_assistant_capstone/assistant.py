# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Капстоун: дешёвый мультимодальный ассистент. RAG на русских эмбеддингах плюс зрение, с замерами.
import os
import time
import math
import httpx

key = os.environ["OPENROUTER_API_KEY"]
H = {"Authorization": f"Bearer {key}"}
BASE = "https://openrouter.ai/api/v1"

def embed(texts):
    # Русскоязычные эмбеддинги через мультиязычную модель bge-m3.
    r = httpx.post(f"{BASE}/embeddings", headers=H, timeout=60,
                   json={"model": "baai/bge-m3", "input": texts}).json()
    return [d["embedding"] for d in r["data"]]

def cos(a, b):
    # Косинусная близость двух векторов.
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb)

# Небольшая база знаний из фактов серии.
KB = [
    "OpenRouter это единый OpenAI-совместимый роутер к десяткам моделей одним ключом.",
    "Оплата картой РФ обычно не проходит, надёжный путь пополнения это криптовалюта USDC.",
    "Кэш промптов удешевляет повторный общий контекст, а session_id держит кэш тёплым.",
    "Через один ключ доступны текст, генерация картинок, транскрипция и синтез речи.",
]

t0 = time.time()
kb_vecs = embed(KB)   # эмбеддинги базы считаем один раз
cost = 0.0

# 1. Текстовый вопрос: эмбеддинг запроса, поиск ближайших фактов, ответ дешёвой моделью.
q = "Как из России оплатить OpenRouter?"
qv = embed([q])[0]
ranked = sorted(range(len(KB)), key=lambda i: cos(qv, kb_vecs[i]), reverse=True)
ctx = "\n".join(KB[i] for i in ranked[:2])   # берём топ-2 факта как контекст
ans = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=60, json={
    "model": "openai/gpt-4o-mini",
    "max_tokens": 80,
    "usage": {"include": True},
    "messages": [
        {"role": "system", "content": "Отвечай кратко и только по контексту."},
        {"role": "user", "content": f"Контекст:\n{ctx}\n\nВопрос: {q}"},
    ],
}).json()
cost += ans["usage"]["cost"]
print("вопрос:", q)
print("ответ :", ans["choices"][0]["message"]["content"].strip())

# 2. Мультимодальность: генерируем картинку и тут же спрашиваем о ней у зрячей модели.
img = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=120, json={
    "model": "google/gemini-2.5-flash-image",
    "modalities": ["image", "text"],
    "messages": [{"role": "user", "content": "Синий круг на белом фоне"}],
}).json()
cost += img["usage"]["cost"]
data_url = img["choices"][0]["message"]["images"][0]["image_url"]["url"]
vis = httpx.post(f"{BASE}/chat/completions", headers=H, timeout=60, json={
    "model": "openai/gpt-4o-mini",
    "max_tokens": 40,
    "usage": {"include": True},
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "Что на картинке? Одним предложением."},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]}],
}).json()
cost += vis["usage"]["cost"]
print("зрение:", vis["choices"][0]["message"]["content"].strip())

# Замеры: суммарная стоимость и время всего сценария.
print(f"итого стоимость: ${cost:.5f}, время: {time.time() - t0:.1f}s")
