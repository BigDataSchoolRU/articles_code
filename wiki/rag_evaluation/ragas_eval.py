# ragas 0.4.3 (Collections API), ollama 0.40.13, модели qwen2.5:7b и nomic-embed-text, прогнано на стенде 2026-11-06
# Метрики генерации RAG: для двух retriever'ов (top-3 и top-1) генерируем ответ и считаем
# Faithfulness (ответ опирается на контекст) и Context Recall (контекст покрывает эталон).
import asyncio
import json
import math
import sys
import time
import urllib.request

from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.metrics.collections import ContextRecall, Faithfulness

OLLAMA = "http://localhost:11434"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
EMBED_MODEL = "nomic-embed-text"

# Ollama отдаёт OpenAI-совместимый API на /v1, ключ не проверяется, но клиент требует строку
client = AsyncOpenAI(base_url=OLLAMA + "/v1", api_key="ollama")
# судья: та же qwen2.5:7b, temperature 0 ради повторяемости
judge = llm_factory(MODEL, client=client, temperature=0, max_tokens=1024)
faithfulness = Faithfulness(llm=judge)
context_recall = ContextRecall(llm=judge)


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def embed(texts):
    req = urllib.request.Request(
        OLLAMA + "/api/embed",
        data=json.dumps({"model": EMBED_MODEL, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["embeddings"]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


corpus = load_jsonl("corpus.jsonl")
dataset = load_jsonl("dataset.jsonl")
doc_vecs = embed(["search_document: " + d["text"] for d in corpus])


def retrieve(question, k):
    # тот же поиск, что в retrieval_metrics.py: косинусная близость, первые k фрагментов
    qvec = embed(["search_query: " + question])[0]
    scored = sorted(zip(corpus, doc_vecs), key=lambda p: cosine(qvec, p[1]), reverse=True)
    return [d for d, _ in scored[:k]]


PROMPT = (
    "Ответь на вопрос двумя-тремя предложениями, опираясь только на контекст. "
    "Если в контексте нет нужных сведений, так и скажи.\n\nКонтекст:\n{context}\n\nВопрос: {question}"
)


async def generate(question, contexts):
    resp = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": PROMPT.format(context="\n".join(contexts), question=question)}],
        temperature=0,
        seed=42,
        max_tokens=200,
    )
    return resp.choices[0].message.content.strip()


def fmt(x):
    return "nan" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.2f}"


async def main():
    for name, k in [("нормальный top-3", 3), ("испорченный top-1", 1)]:
        print(f"\n### retriever {name}", flush=True)
        f_vals, r_vals = [], []
        for q in dataset:
            docs = retrieve(q["question"], k)
            contexts = [d["text"] for d in docs]
            t = time.time()
            answer = await generate(q["question"], contexts)
            t_gen = time.time() - t

            # Faithfulness: доля утверждений ответа, которые выводятся из найденного контекста
            t = time.time()
            f = await faithfulness.ascore(user_input=q["question"], response=answer, retrieved_contexts=contexts)
            t_f = time.time() - t
            # Context Recall: доля утверждений эталона, которые подтверждаются найденным контекстом
            t = time.time()
            r = await context_recall.ascore(user_input=q["question"], retrieved_contexts=contexts, reference=q["reference"])
            t_r = time.time() - t

            f_vals.append(f.value)
            r_vals.append(r.value)
            print(f"{q['id']} контекст={','.join(d['id'] for d in docs)}", flush=True)
            print(f"   ответ: {answer}", flush=True)
            print(f"   faithfulness={fmt(f.value)} context_recall={fmt(r.value)}"
                  f"  (генерация {t_gen:.0f} с, faithfulness {t_f:.0f} с, context_recall {t_r:.0f} с)", flush=True)

        def mean(vals):
            ok = [v for v in vals if v is not None and not math.isnan(v)]
            return sum(ok) / len(ok) if ok else float("nan")

        print(f"ИТОГ {name}: faithfulness={fmt(mean(f_vals))} context_recall={fmt(mean(r_vals))}", flush=True)


asyncio.run(main())
