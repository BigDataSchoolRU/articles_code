# rank-bm25 0.2.2, ollama (python client) 0.6.2, модель nomic-embed-text (768 измерений),
# numpy 2.5.2, прогнано на стенде 2026-08-27; rank_constant=60 — дефолт RRF retriever
# в Elasticsearch, формула 1/(k+rank) — по Cormack, Clarke, Buettcher, SIGIR 2009
"""
Reciprocal Rank Fusion (RRF) на своей реализации: два независимых ранжированных
списка (BM25 и векторный поиск) сливаются в один по формуле 1/(k+rank), где
rank — позиция документа в исходном списке (с 1), а k — константа, гасящая
влияние низких позиций. Документ, которого нет в списке вообще, вклада в его
итоговый score не даёт — это и отличает RRF от score-based слияния, где
пришлось бы нормализовать несравнимые шкалы (BM25-score и косинус).
"""
import ollama
import numpy as np
from rank_bm25 import BM25Okapi

EMBED_MODEL = "nomic-embed-text"
RANK_CONSTANT = 60  # k в формуле RRF, дефолт Elasticsearch RRF retriever

CORPUS = [
    "PostgreSQL использует WAL для журналирования изменений и восстановления после сбоя",
    "Apache Kafka хранит события в партициях топика и гарантирует порядок только внутри партиции",
    "Обучение нейронной сети на GPU ускоряется за счёт параллельных матричных вычислений",
    "Квантование весов модели снижает объём памяти и ускоряет инференс на слабом железе",
    "Docker Compose поднимает несколько контейнеров одной командой по файлу конфигурации",
    "Vector database хранит эмбеддинги и ищет ближайших соседей по косинусному расстоянию",
    "BM25 — вероятностная модель ранжирования, учитывающая частоту термина и длину документа",
    "Дистилляция модели переносит знания большой сети в компактную с сохранением качества",
    "Индекс HNSW строит граф ближайших соседей для быстрого приближённого поиска векторов",
    "Репликация PostgreSQL с wal_level=logical рассылает построчные изменения подписчикам",
]

QUERY = "как сделать модель быстрее на слабом оборудовании без GPU"

# Сколько документов каждый ретривер отдаёт наружу до слияния — в проде это
# rank_window_size, а не полный размер корпуса.
TOP_K_PER_RETRIEVER = 5


def bm25_ranked_docs(query: str, corpus: list[str], top_k: int) -> list[str]:
    tokenized_corpus = [doc.lower().split() for doc in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())
    ranked = sorted(zip(corpus, scores), key=lambda item: item[1], reverse=True)
    return [doc for doc, score in ranked[:top_k] if score > 0]


def embed(text: str, task_prefix: str) -> np.ndarray:
    r = ollama.embed(model=EMBED_MODEL, input=f"{task_prefix}: {text}")
    return np.array(r["embeddings"][0], dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def vector_ranked_docs(query: str, corpus: list[str], top_k: int) -> list[str]:
    query_vec = embed(query, "search_query")
    corpus_vecs = {doc: embed(doc, "search_document") for doc in corpus}
    ranked = sorted(corpus, key=lambda doc: cosine_similarity(query_vec, corpus_vecs[doc]), reverse=True)
    return ranked[:top_k]


def reciprocal_rank_fusion(ranked_lists: list[list[str]], k: int = RANK_CONSTANT) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranked_list in ranked_lists:
        for position, doc in enumerate(ranked_list, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def main():
    print(f"Запрос: {QUERY!r}, rank_constant={RANK_CONSTANT}\n")

    bm25_docs = bm25_ranked_docs(QUERY, CORPUS, TOP_K_PER_RETRIEVER)
    vector_docs = vector_ranked_docs(QUERY, CORPUS, TOP_K_PER_RETRIEVER)

    print("BM25 топ-5 (позиция важна, score — нет):")
    for rank, doc in enumerate(bm25_docs, start=1):
        print(f"  {rank}. {doc}")

    print("\nВекторный поиск топ-5:")
    for rank, doc in enumerate(vector_docs, start=1):
        print(f"  {rank}. {doc}")

    fused = reciprocal_rank_fusion([bm25_docs, vector_docs])

    print("\n--- После RRF-слияния ---")
    for rank, (doc, score) in enumerate(fused, start=1):
        bm25_pos = bm25_docs.index(doc) + 1 if doc in bm25_docs else "—"
        vector_pos = vector_docs.index(doc) + 1 if doc in vector_docs else "—"
        print(f"{rank}. [rrf={score:.5f}, bm25_rank={bm25_pos}, vector_rank={vector_pos}] {doc}")


if __name__ == "__main__":
    main()
