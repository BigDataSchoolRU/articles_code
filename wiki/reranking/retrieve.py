# ollama 0.6.2, модель nomic-embed-text (768 измерений), прогнано на стенде 2026-08-26
# nomic-embed-text асимметричная: без префиксов задачи cosine similarity считается
# некорректно (см. грабли в 02. Wiki/stand.md) — префиксы обязательны

import ollama


def embed_query(text: str) -> list[float]:
    r = ollama.embed(model="nomic-embed-text", input=f"search_query: {text}")
    return r["embeddings"][0]


def embed_document(text: str) -> list[float]:
    r = ollama.embed(model="nomic-embed-text", input=f"search_document: {text}")
    return r["embeddings"][0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b)


def baseline_retrieve(query: str, documents: list[tuple[str, str]], top_n: int):
    """Возвращает top_n документов по косинусному сходству эмбеддингов, отсортированных
    по убыванию сходства. documents — список (id, текст)."""
    query_vec = embed_query(query)
    scored = []
    for doc_id, text in documents:
        doc_vec = embed_document(text)
        scored.append((doc_id, text, cosine_similarity(query_vec, doc_vec)))
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored[:top_n]
