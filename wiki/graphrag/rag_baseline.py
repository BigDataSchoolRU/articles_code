# Проверено на graphrag 3.1.1, Python 3.12.13, Ollama 0.32.9, qwen2.5:7b + nomic-embed-text
"""Наивный векторный RAG на том же корпусе, что и GraphRAG.

Нужен как база для сравнения: показывает, что на multi-hop вопросе
поиск по косинусной близости не собирает ответ, потому что нужные факты
лежат в разных документах и ни один из них не похож на вопрос целиком.
"""

import glob
import os
import time

import numpy as np
import ollama

CHAT_MODEL = "qwen2.5:7b"
EMBED_MODEL = "nomic-embed-text"
TOP_K = int(os.environ.get("TOP_K", "2"))
INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")

QUESTION = (
    "В какую дирекцию банка входит подразделение, "
    "которое обслуживает ООО Северный Ветер?"
)


def load_documents() -> list[tuple[str, str]]:
    """Читает корпус. Каждый файл это один чанк: документы намеренно короткие."""
    docs = []
    for path in sorted(glob.glob(os.path.join(INPUT_DIR, "*.txt"))):
        with open(path, encoding="utf-8") as fh:
            docs.append((os.path.basename(path), fh.read().strip()))
    return docs


def embed(texts: list[str]) -> np.ndarray:
    """Считает эмбеддинги через Ollama и нормирует их для косинусной близости."""
    vectors = [ollama.embeddings(model=EMBED_MODEL, prompt=t)["embedding"] for t in texts]
    matrix = np.array(vectors, dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def retrieve(question: str, docs, doc_vectors: np.ndarray, top_k: int = TOP_K):
    """Отбирает top_k документов по косинусной близости к вопросу."""
    q_vector = embed([question])[0]
    scores = doc_vectors @ q_vector
    order = np.argsort(-scores)[:top_k]
    return [(docs[i][0], docs[i][1], float(scores[i])) for i in order]


def answer(question: str, context_chunks) -> str:
    """Просит модель ответить строго по найденному контексту."""
    context = "\n\n".join(f"[{name}]\n{text}" for name, text, _ in context_chunks)
    prompt = (
        "Отвечай только на русском языке. "
        "Ответь на вопрос, опираясь исключительно на приведённые фрагменты. "
        "Ничего не додумывай: если во фрагментах не хватает данных, "
        "прямо напиши, каких именно связей не хватает.\n\n"
        f"Фрагменты:\n{context}\n\nВопрос: {question}\nОтвет:"
    )
    response = ollama.chat(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.0},
    )
    return response["message"]["content"].strip()


def main() -> None:
    docs = load_documents()
    print(f"Документов в корпусе: {len(docs)}, top_k = {TOP_K}")

    started = time.time()
    doc_vectors = embed([text for _, text in docs])
    index_seconds = time.time() - started
    # Индексация обычного RAG это ровно один вызов эмбеддера на документ,
    # ни одного вызова генеративной модели.
    print(f"Индексация: {index_seconds:.2f} с, вызовов LLM: 0, "
          f"вызовов эмбеддера: {len(docs)}")

    print(f"\nВопрос: {QUESTION}\n")
    found = retrieve(QUESTION, docs, doc_vectors)
    print("Найденные фрагменты:")
    for name, _, score in found:
        print(f"  {name}  близость {score:.3f}")

    print("\nОтвет наивного RAG:")
    print(answer(QUESTION, found))


if __name__ == "__main__":
    main()
