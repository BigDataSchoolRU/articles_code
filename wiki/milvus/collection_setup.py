# pymilvus 2.6.16 (milvus-lite 3.2.1), эмбеддинги Ollama nomic-embed-text (768 измерений), прогнано на стенде 2026-08-30
# Создание коллекции в Milvus Lite: схема, вставка embeddings, построение HNSW-индекса.

import ollama
from pymilvus import MilvusClient, DataType

DB_PATH = "milvus_demo.db"
COLLECTION = "tech_articles"

# Короткие тексты про разные технологии из мира данных и ML, с рубрикой для скалярного фильтра.
DOCUMENTS = [
    ("streaming", "Apache Kafka передаёт события между сервисами через партиционированный лог с гарантией порядка внутри партиции."),
    ("orchestration", "Apache Airflow описывает пайплайны данных как DAG и по расписанию запускает задачи с отслеживанием зависимостей."),
    ("database", "PostgreSQL — реляционная СУБД с поддержкой транзакций ACID и богатым набором индексов, включая GiST и GIN."),
    ("database", "Milvus — распределённая векторная база данных для приближённого поиска ближайших соседей по embedding-векторам."),
    ("ml", "Fine-tuning дообучает предобученную языковую модель на узком датасете, чтобы адаптировать её под конкретную задачу."),
    ("ml", "RAG комбинирует поиск релевантных документов через векторную базу с генерацией ответа языковой моделью."),
    ("orchestration", "LangGraph описывает мультиагентные системы как граф состояний с узлами-исполнителями и условной маршрутизацией."),
    ("streaming", "Debezium через Change Data Capture публикует изменения строк PostgreSQL в топики Kafka в реальном времени."),
]


def embed_document(text: str) -> list[float]:
    # nomic-embed-text асимметричная модель: документы и запросы кодируются с разными префиксами задачи.
    response = ollama.embed(model="nomic-embed-text", input=f"search_document: {text}")
    return response["embeddings"][0]


def main() -> None:
    client = MilvusClient(uri=DB_PATH)

    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)

    # auto_id=False: id проставляем сами, порядковый номер документа в списке DOCUMENTS.
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=768)
    schema.add_field(field_name="category", datatype=DataType.VARCHAR, max_length=32)
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=500)

    client.create_collection(collection_name=COLLECTION, schema=schema)

    rows = []
    for doc_id, (category, text) in enumerate(DOCUMENTS):
        rows.append({
            "id": doc_id,
            "vector": embed_document(text),
            "category": category,
            "text": text,
        })
    client.insert(COLLECTION, rows)
    print(f"вставлено документов: {len(rows)}")

    # HNSW строит граф ближайших соседей поверх embedding-векторов, COSINE — метрика близости.
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 200},
    )
    client.create_index(COLLECTION, index_params)

    # Сегмент переходит из growing в sealed и становится доступен для ANN-поиска только после load.
    client.load_collection(COLLECTION)
    print("индекс построен, коллекция загружена для поиска")


if __name__ == "__main__":
    main()
