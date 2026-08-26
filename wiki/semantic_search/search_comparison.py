# ollama 0.6.2, модель nomic-embed-text (768 измерений), numpy 2.5.2, прогнано на стенде 2026-08-26
"""
Semantic search против поиска по ключевым словам на маленьком корпусе обращений
в техподдержку. Демонстрирует главное отличие техники: запрос без общих слов
с нужным документом находится через эмбеддинги, но не находится через
пересечение слов.
"""
import ollama
import numpy as np

EMBED_MODEL = "nomic-embed-text"

# Корпус — короткие обращения в техподдержку, как они выглядели бы в базе знаний
CORPUS = [
    "Не могу зайти в личный кабинет, забыл пароль",
    "Принтер на третьем этаже не печатает цветные документы",
    "Как получить доступ к общей папке проекта X",
    "Ноутбук зависает при подключении к Wi-Fi в переговорной",
    "Хочу настроить пересылку почты на личный ящик",
    "Не приходят push-уведомления в мобильном приложении",
    "Как продлить лицензию на антивирус",
    "VPN не подключается с домашнего компьютера",
]

# Запрос намеренно не пересекается по словам с целевым документом (#0):
# ни "пароль", ни "кабинет" в запросе нет, но смысл — тот же самый.
QUERY = "Забыла свою кодовую фразу, попасть в свой профиль на сайте не получается"


def embed(text: str, task_prefix: str) -> np.ndarray:
    # nomic-embed-text — асимметричная модель: без префикса задачи
    # (search_query / search_document) similarity между запросом и документом
    # считается некорректно, векторы почти неразличимы по косинусу.
    r = ollama.embeddings(model=EMBED_MODEL, prompt=f"{task_prefix}: {text}")
    return np.array(r["embedding"], dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def keyword_overlap(query: str, doc: str) -> int:
    # Наивный поиск по ключевым словам: пересечение множеств слов без стоп-слов
    stop = {"не", "на", "в", "с", "и", "к", "под", "для", "мой", "моим", "новый"}
    q_words = {w.strip(",.").lower() for w in query.split()} - stop
    d_words = {w.strip(",.").lower() for w in doc.split()} - stop
    return len(q_words & d_words)


def main():
    print(f"Запрос: {QUERY!r}\n")

    query_vec = embed(QUERY, "search_query")
    corpus_vecs = [embed(doc, "search_document") for doc in CORPUS]

    semantic_ranked = sorted(
        zip(CORPUS, corpus_vecs),
        key=lambda item: cosine_similarity(query_vec, item[1]),
        reverse=True,
    )
    overlaps = [(doc, keyword_overlap(QUERY, doc)) for doc in CORPUS]
    keyword_ranked = sorted(overlaps, key=lambda item: item[1], reverse=True)
    max_overlap = keyword_ranked[0][1]

    print("Semantic search (cosine similarity по эмбеддингам), топ-3:")
    for doc, vec in semantic_ranked[:3]:
        print(f"  {cosine_similarity(query_vec, vec):.4f}  {doc}")

    print("\nПоиск по ключевым словам (пересечение множеств слов), топ-3:")
    for doc, overlap in keyword_ranked[:3]:
        print(f"  overlap={overlap}  {doc}")

    top_semantic = semantic_ranked[0][0]
    print(f"\nЦелевой документ: {CORPUS[0]!r}")
    print(f"Semantic search нашёл его первым: {top_semantic == CORPUS[0]}")
    if max_overlap == 0:
        print("Keyword search: пересечений слов нет ни с одним документом — "
              "ранжировать нечем, результат недостоверен")
    else:
        print(f"Keyword search нашёл его первым: {keyword_ranked[0][0] == CORPUS[0]}")


if __name__ == "__main__":
    main()
