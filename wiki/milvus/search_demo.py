# pymilvus 2.6.16 (milvus-lite 3.2.1), эмбеддинги Ollama nomic-embed-text (768 измерений), прогнано на стенде 2026-08-30
# ANN-поиск и поиск с фильтром по скалярному полю в уже наполненной коллекции Milvus Lite.
# Запускать после collection_setup.py — коллекция читается из того же файла базы.

import ollama
from pymilvus import MilvusClient

DB_PATH = "milvus_demo.db"
COLLECTION = "tech_articles"


def embed_query(text: str) -> list[float]:
    # Для запроса используется префикс задачи "search_query: ", для документов был "search_document: ".
    response = ollama.embed(model="nomic-embed-text", input=f"search_query: {text}")
    return response["embeddings"][0]


def main() -> None:
    client = MilvusClient(uri=DB_PATH)
    # Milvus Lite не хранит состояние загрузки между процессами: новое подключение к тому же
    # файлу базы видит коллекцию released, и без повторного load() поиск падает с ошибкой.
    client.load_collection(COLLECTION)

    query_text = "как построить мультиагентную систему для ИИ-агентов"
    query_vector = embed_query(query_text)

    print(f"запрос: {query_text!r}\n")

    print("-- обычный ANN-поиск (топ-3 по всей коллекции) --")
    plain_results = client.search(
        COLLECTION,
        data=[query_vector],
        limit=3,
        output_fields=["category", "text"],
    )
    for hit in plain_results[0]:
        entity = hit["entity"]
        print(f"distance={hit['distance']:.4f}  [{entity['category']}]  {entity['text']}")

    print("\n-- поиск с фильтром по скалярному полю (category == 'orchestration') --")
    filtered_results = client.search(
        COLLECTION,
        data=[query_vector],
        limit=3,
        filter="category == 'orchestration'",
        output_fields=["category", "text"],
    )
    for hit in filtered_results[0]:
        entity = hit["entity"]
        print(f"distance={hit['distance']:.4f}  [{entity['category']}]  {entity['text']}")


if __name__ == "__main__":
    main()
