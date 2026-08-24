# chromadb 1.5.9, ollama 0.32.13, модель nomic-embed-text (768 измерений).
# Прогнано на стенде 2026-08-24, Python 3.12.13, macOS 26.5.2 arm64.
"""Базовый сценарий ChromaDB: постоянная коллекция, вставка документов и поиск по смыслу.

Эмбеддинги считает локальная Ollama, ключи и внешние сервисы не нужны.
"""

import shutil
import time
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

DB_PATH = Path(__file__).parent / "chroma_data"
OLLAMA_URL = "http://localhost:11434"
MODEL = "nomic-embed-text"

# Чистим прошлый прогон, чтобы цифры вставки были честными, а не поверх старой коллекции.
if DB_PATH.exists():
    shutil.rmtree(DB_PATH)

# PersistentClient пишет на диск: SQLite под документы и метаданные, отдельный файл под индекс.
client = chromadb.PersistentClient(path=str(DB_PATH))

# Функция эмбеддинга живёт на уровне коллекции: Chroma сама вызовет её и на вставке, и на запросе.
ollama_ef = OllamaEmbeddingFunction(url=OLLAMA_URL, model_name=MODEL)

# Имя коллекции проверяется строго: 3-512 символов из [a-zA-Z0-9._-].
collection = client.create_collection(
    name="bigdata_terms",
    embedding_function=ollama_ef,
    configuration={"hnsw": {"space": "cosine"}},  # по умолчанию используется l2
)

documents = [
    "Apache Kafka это распределённый лог сообщений с разбиением топиков на партиции.",
    "Apache Flink обрабатывает неограниченные потоки событий с состоянием и точным временем.",
    "Apache Airflow оркестрирует пакетные конвейеры данных в виде направленного ациклического графа.",
    "Apache Spark выполняет распределённые вычисления над датафреймами в памяти кластера.",
    "ClickHouse это колоночная СУБД для аналитических запросов по миллиардам строк.",
    "Greenplum это массивно-параллельная аналитическая база на основе PostgreSQL.",
    "Векторная база данных ищет ближайших соседей по косинусной близости эмбеддингов.",
    "HNSW строит многослойный граф соседей и даёт приближённый поиск за логарифмическое время.",
    "RAG подмешивает найденные фрагменты документов в промпт языковой модели.",
    "Эмбеддинг это плотный числовой вектор, который кодирует смысл текста.",
    "Debezium читает журнал транзакций базы и превращает изменения строк в поток событий.",
    "Iceberg хранит снимки таблицы в метаданных и даёт атомарные коммиты поверх озера данных.",
]

metadatas = [
    {"category": "streaming", "year": 2011, "level": "middle"},
    {"category": "streaming", "year": 2014, "level": "senior"},
    {"category": "orchestration", "year": 2014, "level": "junior"},
    {"category": "batch", "year": 2010, "level": "middle"},
    {"category": "olap", "year": 2016, "level": "middle"},
    {"category": "olap", "year": 2005, "level": "senior"},
    {"category": "ai", "year": 2019, "level": "junior"},
    {"category": "ai", "year": 2016, "level": "senior"},
    {"category": "ai", "year": 2020, "level": "middle"},
    {"category": "ai", "year": 2013, "level": "junior"},
    {"category": "cdc", "year": 2016, "level": "middle"},
    {"category": "lakehouse", "year": 2018, "level": "senior"},
]

ids = [f"doc_{i:02d}" for i in range(len(documents))]

# Вставка одной пачкой: документы уходят в журнал записи, эмбеддинги считает Ollama.
start = time.time()
collection.add(ids=ids, documents=documents, metadatas=metadatas)
insert_seconds = time.time() - start

print(f"документов в коллекции: {collection.count()}")
print(f"вставка {len(documents)} документов: {insert_seconds:.2f} с")
print(f"на документ: {insert_seconds / len(documents):.2f} с")

# Запрос текстом: Chroma сама векторизует строку той же функцией эмбеддинга.
start = time.time()
result = collection.query(
    query_texts=["как искать похожие тексты по смыслу"],
    n_results=3,
    include=["documents", "metadatas", "distances"],
)
query_seconds = time.time() - start

print(f"\nзапрос выполнен за {query_seconds * 1000:.1f} мс")
for doc, meta, dist in zip(
    result["documents"][0], result["metadatas"][0], result["distances"][0]
):
    print(f"  {dist:.4f}  [{meta['category']}]  {doc}")

# Размерность вектора берём из самой коллекции, а не из головы.
peek = collection.get(ids=["doc_00"], include=["embeddings"])
print(f"\nразмерность вектора: {len(peek['embeddings'][0])}")
