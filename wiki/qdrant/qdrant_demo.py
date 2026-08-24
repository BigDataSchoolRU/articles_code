# Прогон: Qdrant 1.19.0 в Docker, qdrant-client 1.19.0, Ollama 0.32.9, модель nomic-embed-text
import httpx
from qdrant_client import QdrantClient, models

OLLAMA = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
COLLECTION = "bds_courses"

# Мини-корпус: описание курса и тема, по которой потом будем фильтровать
DOCS = [
    ("Администрирование кластера Apache Kafka: брокеры, топики, реплики", "streaming"),
    ("Потоковая обработка данных с помощью Apache Flink и оконных функций", "streaming"),
    ("Эксплуатация Apache NiFi: процессоры, очереди и обратное давление", "streaming"),
    ("Построение хранилища данных на ClickHouse: движки таблиц и партиции", "dwh"),
    ("Проектирование online-хранилищ данных на StarRocks", "dwh"),
    ("Greenplum для инженеров данных: распределение и сегменты", "dwh"),
    ("ИИ-агенты для бизнес-процессов: LLM, инструменты и векторный поиск", "ai"),
    ("Нейронные сети на Python: обучение и инференс моделей", "ai"),
]


def embed(text: str) -> list[float]:
    # Ollama возвращает вектор фиксированной длины 768 для nomic-embed-text
    r = httpx.post(OLLAMA, json={"model": EMBED_MODEL, "prompt": text}, timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]


client = QdrantClient(url="http://localhost:6333")
dim = len(embed("проверка размерности"))
print(f"Размерность вектора модели {EMBED_MODEL}: {dim}")

# Коллекция с косинусной метрикой, явными параметрами HNSW и скалярным квантованием
client.delete_collection(COLLECTION)
client.create_collection(
    collection_name=COLLECTION,
    vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
    quantization_config=models.ScalarQuantization(
        scalar=models.ScalarQuantizationConfig(
            type=models.ScalarType.INT8, quantile=0.99, always_ram=True
        )
    ),
)

# Индекс по полю payload создаётся ДО загрузки точек: тогда HNSW получит рёбра под фильтр
client.create_payload_index(
    collection_name=COLLECTION,
    field_name="topic",
    field_schema=models.PayloadSchemaType.KEYWORD,
)

points = [
    models.PointStruct(id=i, vector=embed(text), payload={"title": text, "topic": topic})
    for i, (text, topic) in enumerate(DOCS)
]
client.upsert(collection_name=COLLECTION, points=points, wait=True)
print(f"Загружено точек: {client.count(COLLECTION, exact=True).count}")

query = "как обрабатывать события в реальном времени"
qvec = embed(query)

print(f"\nЗапрос: {query}")
print("--- поиск без фильтра ---")
for p in client.query_points(COLLECTION, query=qvec, limit=3, with_payload=True).points:
    print(f"  {p.score:.4f}  [{p.payload['topic']}]  {p.payload['title']}")

# Тот же запрос, но с жёстким условием по payload: фильтр применяется во время обхода графа
print("--- поиск с фильтром topic=dwh ---")
flt = models.Filter(must=[models.FieldCondition(key="topic", match=models.MatchValue(value="dwh"))])
for p in client.query_points(COLLECTION, query=qvec, limit=3, query_filter=flt, with_payload=True).points:
    print(f"  {p.score:.4f}  [{p.payload['topic']}]  {p.payload['title']}")

info = client.get_collection(COLLECTION)
print(f"\nСтатус коллекции: {info.status}, точек: {info.points_count}, векторов в индексе: {info.indexed_vectors_count}")

# Почему indexed_vectors_count равен нулю: до порога индексации Qdrant ищет полным перебором
opt = info.config.optimizer_config
print(f"Порог индексации, КБ: {opt.indexing_threshold}, сегментов по умолчанию: {opt.default_segment_number}")
print(f"Индексы по payload: {info.payload_schema}")
