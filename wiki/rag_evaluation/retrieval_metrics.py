# ollama 0.40.13, модель nomic-embed-text, Python 3.12.3, прогнано на стенде 2026-11-06
# Метрики поиска RAG без LLM: hit rate@k, recall@k, MRR и nDCG@k по размеченным фрагментам.
# Два retriever'а на одном индексе: нормальный (top-3) и испорченный (top-1).
import json
import math
import sys
import urllib.request

OLLAMA = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"


def embed(texts):
    # nomic-embed-text обучена с префиксами задачи, без них качество поиска хуже
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


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


corpus = load_jsonl("corpus.jsonl")
dataset = load_jsonl("dataset.jsonl")

# индекс: эмбеддинг каждого фрагмента базы знаний
doc_vecs = embed(["search_document: " + d["text"] for d in corpus])
query_vecs = embed(["search_query: " + q["question"] for q in dataset])


def ranking(qvec):
    # полный список id фрагментов по убыванию косинусной близости к вопросу
    scored = sorted(zip(corpus, doc_vecs), key=lambda p: cosine(qvec, p[1]), reverse=True)
    return [d["id"] for d, _ in scored]


# метрики по классическим определениям IR, relevant это разметка из dataset.jsonl
def hit_rate(found, relevant):
    return 1.0 if set(found) & set(relevant) else 0.0


def recall(found, relevant):
    return len(set(found) & set(relevant)) / len(relevant)


def reciprocal_rank(found, relevant):
    for rank, doc_id in enumerate(found, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg(found, relevant):
    dcg = sum(1.0 / math.log2(i + 2) for i, d in enumerate(found) if d in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), len(found))))
    return dcg / ideal


rankings = {q["id"]: ranking(v) for q, v in zip(dataset, query_vecs)}

print("вопрос | эталон | top-3 по близости")
for q in dataset:
    print(q["id"], "|", ",".join(q["relevant"]), "|", ",".join(rankings[q["id"]][:3]))

for name, k in [("нормальный top-3", 3), ("испорченный top-1", 1)]:
    rows = []
    for q in dataset:
        found = rankings[q["id"]][:k]
        rows.append([hit_rate(found, q["relevant"]), recall(found, q["relevant"]),
                     reciprocal_rank(found, q["relevant"]), ndcg(found, q["relevant"])])
    avg = [sum(col) / len(rows) for col in zip(*rows)]
    print(f"\nretriever {name}")
    print(f"  hit_rate@{k} = {avg[0]:.2f}")
    print(f"  recall@{k}   = {avg[1]:.2f}")
    print(f"  MRR@{k}      = {avg[2]:.2f}")
    print(f"  nDCG@{k}     = {avg[3]:.2f}")
    print("  по вопросам recall:", " ".join(f"{q['id']}={r[1]:.2f}" for q, r in zip(dataset, rows)))

sys.stdout.flush()
