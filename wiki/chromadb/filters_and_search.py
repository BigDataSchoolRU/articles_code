# chromadb 1.5.9, ollama 0.32.13, модель nomic-embed-text (768 измерений).
# Прогнано на стенде 2026-08-24, Python 3.12.13, macOS 26.5.2 arm64.
# Запускать после basic_collection.py: коллекция bigdata_terms уже должна лежать на диске.
"""Фильтры ChromaDB: отбор по метаданным и поиск по тексту документа без эмбеддингов."""

from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

DB_PATH = Path(__file__).parent / "chroma_data"
OLLAMA_URL = "http://localhost:11434"
MODEL = "nomic-embed-text"

# Клиент переоткрывает ту же папку: данные пережили завершение процесса.
client = chromadb.PersistentClient(path=str(DB_PATH))
ollama_ef = OllamaEmbeddingFunction(url=OLLAMA_URL, model_name=MODEL)
collection = client.get_collection(name="bigdata_terms", embedding_function=ollama_ef)

print(f"коллекция открыта заново, документов: {collection.count()}")

# 1. Векторный поиск с предфильтром по метаданным.
# Chroma сначала отсекает записи по where, потом ищет соседей внутри остатка.
print("\n=== векторный поиск только по category=ai ===")
res = collection.query(
    query_texts=["распределённая обработка данных"],
    n_results=3,
    where={"category": "ai"},
    include=["documents", "metadatas", "distances"],
)
for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
    print(f"  {dist:.4f}  [{meta['category']}/{meta['year']}]  {doc}")

# 2. Составной фильтр: два условия через $and, диапазон через $gte, перечисление через $in.
print("\n=== составной фильтр: year >= 2014 и level из (middle, senior) ===")
res = collection.get(
    where={
        "$and": [
            {"year": {"$gte": 2014}},
            {"level": {"$in": ["middle", "senior"]}},
        ]
    },
    include=["documents", "metadatas"],
)
for doc, meta in zip(res["documents"], res["metadatas"]):
    print(f"  [{meta['year']}/{meta['level']}]  {doc[:60]}...")
print(f"  всего попало: {len(res['ids'])}")

# 3. Полнотекстовый фильтр по телу документа. Эмбеддинги здесь не участвуют вообще.
print("\n=== подстрока в тексте документа: $contains 'Apache' ===")
res = collection.get(where_document={"$contains": "Apache"}, include=["documents"])
print(f"  найдено документов: {len(res['ids'])}")
for doc in res["documents"]:
    print(f"  {doc[:60]}...")

# 4. Регулярное выражение по телу документа, появилось в ветке 1.5.
print("\n=== регулярное выражение: $regex 'парти|снимк' ===")
res = collection.get(where_document={"$regex": "парти|снимк"}, include=["documents"])
for doc in res["documents"]:
    print(f"  {doc[:70]}...")

# 5. Векторный поиск плюс фильтр по тексту сразу: сужаем и по смыслу, и по подстроке.
print("\n=== смысл плюс подстрока: запрос про потоки, только документы со словом 'поток' ===")
res = collection.query(
    query_texts=["обработка событий в реальном времени"],
    n_results=5,
    where_document={"$contains": "поток"},
    include=["documents", "distances"],
)
for doc, dist in zip(res["documents"][0], res["distances"][0]):
    print(f"  {dist:.4f}  {doc[:65]}...")
