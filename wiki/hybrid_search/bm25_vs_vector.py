# rank-bm25 0.2.2, ollama (python client) 0.6.2, модель nomic-embed-text (768 измерений),
# numpy 2.5.2, прогнано на стенде 2026-08-27
"""
Лексический поиск (BM25) и векторный поиск (эмбеддинги) по одному и тому же
корпусу и одному запросу. Показывает, почему их верхние строки расходятся:
BM25 ранжирует по совпадению слов и не видит отрицания и синонимов, векторный
поиск ранжирует по смыслу и не видит точного термина, если он не встретился
в достаточно похожем контексте. Это расхождение и есть причина, зачем нужен
fusion-слой гибридного поиска — см. rrf_fusion.py.
"""
import ollama
import numpy as np
from rank_bm25 import BM25Okapi

EMBED_MODEL = "nomic-embed-text"

# Корпус — короткие заметки из базы знаний дата-инженера
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

# Запрос лексически пересекается с документом про обучение на GPU (слово "GPU"),
# хотя по смыслу спрашивает об обратном — как обойтись без GPU.
QUERY = "как сделать модель быстрее на слабом оборудовании без GPU"


def bm25_rank(query: str, corpus: list[str]) -> list[tuple[str, float]]:
    tokenized_corpus = [doc.lower().split() for doc in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())
    ranked = sorted(zip(corpus, scores), key=lambda item: item[1], reverse=True)
    return ranked


def embed(text: str, task_prefix: str) -> np.ndarray:
    # nomic-embed-text асимметричная: без префикса задачи (search_query /
    # search_document) косинусное сходство запрос-документ считается некорректно.
    r = ollama.embed(model=EMBED_MODEL, input=f"{task_prefix}: {text}")
    return np.array(r["embeddings"][0], dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def vector_rank(query: str, corpus: list[str]) -> list[tuple[str, float]]:
    query_vec = embed(query, "search_query")
    corpus_vecs = [embed(doc, "search_document") for doc in corpus]
    ranked = sorted(
        zip(corpus, corpus_vecs),
        key=lambda item: cosine_similarity(query_vec, item[1]),
        reverse=True,
    )
    return [(doc, cosine_similarity(query_vec, vec)) for doc, vec in ranked]


def main():
    print(f"Запрос: {QUERY!r}\n")

    print("--- BM25 (лексический) топ-5 ---")
    for rank, (doc, score) in enumerate(bm25_rank(QUERY, CORPUS)[:5], start=1):
        print(f"{rank}. [{score:.3f}] {doc}")

    print("\n--- Векторный поиск (семантический) топ-5 ---")
    for rank, (doc, score) in enumerate(vector_rank(QUERY, CORPUS)[:5], start=1):
        print(f"{rank}. [{score:.3f}] {doc}")


if __name__ == "__main__":
    main()
