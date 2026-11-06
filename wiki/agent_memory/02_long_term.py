# langgraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-ollama 1.1.0, ollama 0.40.13, модели qwen2.5:7b и nomic-embed-text, прогнано на стенде 2026-11-06
"""Долговременная память агента: хранилище Store между сессиями.

История треда живёт, пока жив тред. Чтобы агент узнал пользователя в новой сессии, факты о нём
надо вынести в отдельное хранилище. В LangGraph это Store: записи лежат в пространстве имён
(namespace, кортеж строк) под ключом, значение это словарь, а семантический индекс по полю text
позволяет искать записи по смыслу запроса.

Граф проходит цикл памяти на каждой реплике:
  recall        достаём из Store до трёх записей, близких к реплике (чтение);
  call_model    отвечаем, подставив найденное в системный промпт;
  write_memory  та же модель выписывает из реплики устойчивые факты, и они ложатся в Store (запись).
Пространство имён ("memories", user_id) изолирует пользователей друг от друга.
"""
import os
import sys
import time
import uuid
from dataclasses import dataclass

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.runtime import Runtime
from langgraph.store.sqlite import SqliteStore

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "long_term.sqlite")

llm = ChatOllama(model=MODEL, base_url=OLLAMA, temperature=0, seed=42,
                 num_predict=60, num_ctx=4096, keep_alive="60m")
embeddings = OllamaEmbeddings(model="nomic-embed-text", base_url=OLLAMA)


@dataclass
class Context:
    user_id: str  # кто говорит; приходит снаружи графа, а не из истории сообщений


class State(MessagesState):
    recalled: list[str]


timings = {}


def namespace(runtime):
    return ("memories", runtime.context.user_id)


def recall(state: State, runtime: Runtime[Context]):
    started = time.time()
    query = state["messages"][-1].content
    items = runtime.store.search(namespace(runtime), query=query, limit=3)
    timings["recall"] = time.time() - started
    print(f"  recall: найдено {len(items)} записей в {namespace(runtime)}")
    for item in items:
        print(f"    score {item.score:.3f}  {item.value['text']}")
    return {"recalled": [item.value["text"] for item in items]}


def call_model(state: State, runtime: Runtime[Context]):
    started = time.time()
    known = "\n".join(f"- {fact}" for fact in state["recalled"]) or "- ничего"
    system = ("Ты ассистент дата-инженера. Отвечай кратко, одним предложением. "
              "Опирайся только на известное о пользователе, если факта нет, скажи, что не знаешь.\n"
              f"Известно о пользователе из прошлых сессий:\n{known}")
    reply = llm.invoke([("system", system), *state["messages"]])
    timings["call_model"] = time.time() - started
    timings["prompt_tokens"] = reply.response_metadata.get("prompt_eval_count")
    return {"messages": [reply]}


EXTRACT = ("Выпиши из реплики пользователя устойчивые факты о нём самом: имя, работа, инструменты, "
           "предпочтения. Каждый факт отдельной строкой, коротко, от третьего лица, без нумерации. "
           "Вопросы и просьбы фактами не считаются. Если фактов нет, ответь одним словом: НЕТ.\n\n"
           "Реплика: ")


def write_memory(state: State, runtime: Runtime[Context]):
    # запись в горячем пути: отдельный вызов модели на каждую реплику
    started = time.time()
    user_text = state["messages"][-2].content
    out = llm.invoke([("user", EXTRACT + user_text)]).content.strip()
    facts = [line.strip("-• ").strip() for line in out.splitlines() if line.strip()]
    facts = [f for f in facts if f.upper().rstrip(".") != "НЕТ"]
    for fact in facts:
        runtime.store.put(namespace(runtime), uuid.uuid4().hex, {"text": fact})
    timings["write_memory"] = time.time() - started
    print(f"  write_memory: записано {len(facts)}" + "".join(f"\n    + {f}" for f in facts))
    return {}


def session(graph, user_id, thread_id, text):
    print(f"\n=== пользователь {user_id}, тред {thread_id} ===")
    print(f"  > {text}")
    out = graph.invoke({"messages": [("user", text)]},
                       {"configurable": {"thread_id": thread_id}},
                       context=Context(user_id=user_id))
    print(f"  < {out['messages'][-1].content.strip()}")
    print(f"  время: recall {timings['recall']:.1f} с, call_model {timings['call_model']:.1f} с "
          f"(токенов промпта {timings['prompt_tokens']}), write_memory {timings['write_memory']:.1f} с")


if os.path.exists(DB):
    os.remove(DB)

builder = StateGraph(State, context_schema=Context)
builder.add_node("recall", recall)
builder.add_node("call_model", call_model)
builder.add_node("write_memory", write_memory)
builder.add_edge(START, "recall")
builder.add_edge("recall", "call_model")
builder.add_edge("call_model", "write_memory")

# индекс: эмбеддинги nomic-embed-text размерности 768 по полю text значения
index = {"embed": embeddings, "dims": 768, "fields": ["text"]}
with SqliteStore.from_conn_string(DB, index=index) as store:
    store.setup()
    graph = builder.compile(checkpointer=InMemorySaver(), store=store)
    session(graph, "anna", "s1", "Привет! Я Анна, пишу пайплайны на Airflow, а отчёты собираю в ClickHouse.")
    session(graph, "anna", "s2", "В какой базе я собираю отчёты?")
    session(graph, "boris", "s3", "В какой базе я собираю отчёты?")

# новое соединение: долговременная память лежит в файле, а не в процессе
with SqliteStore.from_conn_string(DB, index=index) as store:
    print("\n=== содержимое Store после трёх сессий ===")
    for ns in store.list_namespaces(prefix=("memories",)):
        items = store.search(ns, limit=20)
        print(f"{ns}: {len(items)} записей")
        for item in items:
            print(f"  {item.key[:8]}  {item.value['text']}")
