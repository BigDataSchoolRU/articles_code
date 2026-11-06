# langgraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-ollama 1.1.0, ollama 0.40.13, модели qwen2.5:7b и nomic-embed-text, прогнано на стенде 2026-11-06
"""Управление долговременной памятью: противоречие, обновление по ключу, удаление и TTL.

Запись в память это половина работы. Факты устаревают: пользователь переехал, сменил стек,
отказался от предпочтения. Если каждый новый факт просто дописывать, поиск поднимает в окно и
старую, и новую версию, и модель выбирает между ними сама.

Скрипт сравнивает два способа записи одного и того же изменения:
  append       каждый факт под новым ключом (uuid), старый остаётся;
  upsert       факт о городе всегда лежит под ключом "city", новая запись заменяет старую.
Дальше удаление записи и срок жизни (TTL), который SqliteStore поддерживает, а InMemoryStore нет.
"""
import os
import sys
import time
import uuid

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.store.memory import InMemoryStore
from langgraph.store.sqlite import SqliteStore

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forget.sqlite")

llm = ChatOllama(model=MODEL, base_url=OLLAMA, temperature=0, seed=42,
                 num_predict=40, num_ctx=4096, keep_alive="60m")
index = {"embed": OllamaEmbeddings(model="nomic-embed-text", base_url=OLLAMA),
         "dims": 768, "fields": ["text"]}
QUESTION = "В каком городе я живу?"


def answer(store, ns):
    # чтение: top-3 по смыслу вопроса уходят в системный промпт
    items = store.search(ns, query=QUESTION, limit=3)
    for item in items:
        print(f"    score {item.score:.3f}  [{item.key[:8]}]  {item.value['text']}")
    known = "\n".join(f"- {item.value['text']}" for item in items) or "- ничего"
    started = time.time()
    reply = llm.invoke([("system", "Отвечай кратко, одним предложением, опираясь только на известное "
                                   f"о пользователе.\nИзвестно о пользователе:\n{known}"),
                        ("user", QUESTION)])
    print(f"  > {QUESTION}\n  < {reply.content.strip()}  ({time.time() - started:.1f} с)")


if os.path.exists(DB):
    os.remove(DB)

with SqliteStore.from_conn_string(DB, index=index, ttl={"default_ttl": None}) as store:
    store.setup()

    print("=== 1. append: изменение дописано новой записью ===")
    ns = ("memories", "anna_append")
    store.put(ns, uuid.uuid4().hex, {"text": "Анна живёт в Самаре"})
    store.put(ns, uuid.uuid4().hex, {"text": "Анна пишет пайплайны на Airflow"})
    store.put(ns, uuid.uuid4().hex, {"text": "Анна переехала в Казань"})
    answer(store, ns)

    print("\n=== 2. upsert: у факта о городе один ключ ===")
    ns = ("memories", "anna_upsert")
    store.put(ns, "city", {"text": "Анна живёт в Самаре"})
    first = store.get(ns, "city")
    time.sleep(1)
    store.put(ns, "city", {"text": "Анна живёт в Казани, переехала из Самары"})
    store.put(ns, "stack", {"text": "Анна пишет пайплайны на Airflow"})
    item = store.get(ns, "city")
    print(f"  get(city): {item.value['text']}")
    # перезапись ключа заменяет запись целиком (в SqliteStore это INSERT OR REPLACE),
    # поэтому и created_at становится новым: дату первого появления факта Store не хранит
    print(f"  created_at: {first.created_at:%H:%M:%S} -> {item.created_at:%H:%M:%S}, "
          f"updated_at: {first.updated_at:%H:%M:%S} -> {item.updated_at:%H:%M:%S}")
    print(f"  записей в пространстве имён: {len(store.search(ns, limit=20))}")
    answer(store, ns)

    print("\n=== 3. delete: пользователь попросил забыть город ===")
    store.delete(ns, "city")
    print(f"  get(city): {store.get(ns, 'city')}")
    print("  поиск по тому же вопросу:")
    for item in store.search(ns, query=QUESTION, limit=3):
        print(f"    score {item.score:.3f}  [{item.key}]  {item.value['text']}")

    print("\n=== 4. TTL: временный факт со сроком жизни 0.05 мин (3 с) ===")
    ns = ("memories", "anna_ttl")
    store.put(ns, "trip", {"text": "Анна на этой неделе в командировке в Новосибирске"}, ttl=0.05)
    store.put(ns, "stack", {"text": "Анна пишет пайплайны на Airflow"})
    print(f"  сразу: записей {len(store.search(ns, limit=20))}, get(trip) "
          f"{'есть' if store.get(ns, 'trip') else 'нет'}")
    time.sleep(5)
    print(f"  через 5 с, до очистки: записей {len(store.search(ns, limit=20))}, get(trip) "
          f"{'есть' if store.get(ns, 'trip') else 'нет'}")
    print(f"  sweep_ttl() удалил записей: {store.sweep_ttl()}")
    print(f"  после очистки: записей {len(store.search(ns, limit=20))}, get(trip) "
          f"{'есть' if store.get(ns, 'trip') else 'нет'}")

print(f"\nInMemoryStore.supports_ttl = {InMemoryStore().supports_ttl}, "
      f"SqliteStore.supports_ttl = {SqliteStore.supports_ttl}")
