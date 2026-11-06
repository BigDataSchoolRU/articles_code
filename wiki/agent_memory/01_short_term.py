# langgraph 1.2.20, langgraph-checkpoint-sqlite 3.1.3, langchain-ollama 1.1.0, ollama 0.40.13, модель qwen2.5:7b, прогнано на стенде 2026-11-06
"""Кратковременная память агента: история треда в checkpointer.

Модель сама ничего не помнит между вызовами. Помнит граф LangGraph: после каждого шага
checkpointer сохраняет состояние треда (список сообщений) по ключу thread_id, а на следующем
вызове с тем же thread_id подаёт всю историю обратно в окно модели.

Скрипт показывает три вещи:
1. в одном треде агент отвечает на вопрос о факте из прошлой реплики;
2. состояние лежит в файле SQLite и переживает перезапуск процесса;
3. другой тред того же графа этого факта не знает, а окно растёт с каждой репликой.
"""
import os
import sqlite3
import sys
import time

from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, MessagesState, StateGraph

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "short_term.sqlite")

# temperature 0 и seed ради воспроизводимости, короткий ответ ради времени на CPU
llm = ChatOllama(model=MODEL, base_url=OLLAMA, temperature=0, seed=42,
                 num_predict=40, num_ctx=4096, keep_alive="60m")
SYSTEM = ("system", "Ты ассистент дата-инженера. Отвечай кратко, одним предложением. "
                    "Если не знаешь факта о пользователе, прямо скажи, что не знаешь.")


def call_model(state: MessagesState):
    # в окно уходит вся история треда, которую checkpointer поднял из базы
    reply = llm.invoke([SYSTEM, *state["messages"]])
    return {"messages": [reply]}


def build(conn):
    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_edge(START, "call_model")
    return builder.compile(checkpointer=SqliteSaver(conn))


def ask(graph, thread_id, text):
    config = {"configurable": {"thread_id": thread_id}}
    started = time.time()
    out = graph.invoke({"messages": [("user", text)]}, config)
    reply = out["messages"][-1]
    tokens = reply.response_metadata.get("prompt_eval_count")
    print(f"тред {thread_id} | сообщений в состоянии {len(out['messages']):2d} | "
          f"токенов промпта {tokens:4d} | {time.time() - started:5.1f} с")
    print(f"  > {text}")
    print(f"  < {reply.content.strip()}")


if os.path.exists(DB):
    os.remove(DB)

print("--- процесс 1 ---")
conn = sqlite3.connect(DB, check_same_thread=False)
graph = build(conn)
ask(graph, "anna_1", "Привет! Меня зовут Анна, я пишу пайплайны на Airflow.")
ask(graph, "anna_1", "Как меня зовут и на чём я пишу пайплайны?")
conn.close()

print("--- процесс 2: новое соединение с тем же файлом, граф собран заново ---")
conn = sqlite3.connect(DB, check_same_thread=False)
graph = build(conn)
ask(graph, "anna_1", "Напомни, как меня зовут?")
ask(graph, "anna_2", "Напомни, как меня зовут?")

# что физически лежит в базе: по одному чекпоинту на каждый шаг каждого треда
rows = conn.execute("SELECT thread_id, count(*) FROM checkpoints GROUP BY thread_id ORDER BY thread_id").fetchall()
for thread_id, n in rows:
    print(f"чекпоинтов в базе: тред {thread_id} — {n}")
history = list(graph.get_state_history({"configurable": {"thread_id": "anna_1"}}))
print(f"get_state_history(anna_1): {len(history)} снимков состояния, "
      f"в последнем {len(history[0].values['messages'])} сообщений")
conn.close()
