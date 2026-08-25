# LangGraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1, langchain-ollama 1.1.0,
# Ollama 0.32.13, модель qwen2.5:7b. Прогнано на стенде 2026-08-25.
# Обрыв процесса посреди графа и возобновление с того же thread_id:
# фаза 1 идёт отдельным процессом, который убивается сигналом KILL,
# фаза 2 поднимает работу из чекпоинта, не переделывая уже сделанное.

import os
import signal
import sqlite3
import subprocess
import sys
import time

from langgraph.checkpoint.sqlite import SqliteSaver

from supervisor_graph import build_graph

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "resume.sqlite")
THREAD_ID = "demo-resume"
TASK = "Зачем оркестратору ИИ хранить состояние вне процесса приложения"
CONFIG = {"configurable": {"thread_id": THREAD_ID}}


def open_graph():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn, build_graph(SqliteSaver(conn))


def phase1_worker():
    """Дочерний процесс. Доходит до первого сохранённого шага исполнителя,
    печатает маркер и дальше ждёт, пока его убьют."""
    conn, graph = open_graph()
    for snapshot in graph.stream(
        {"task": TASK, "notes": "", "draft": "", "trace": []},
        CONFIG, stream_mode="values", durability="sync",
    ):
        # как только researcher положил свой результат в состояние,
        # снимок этого состояния уже лежит в SQLite
        if snapshot.get("notes"):
            print("CHECKPOINT_SAVED", flush=True)
            time.sleep(60)
    conn.close()


def phase2_parent():
    """Родитель. Запускает фазу 1, убивает её на середине графа
    и продолжает тот же прогон в своём процессе."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("=== фаза 1: прогон в отдельном процессе ===")
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "worker"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=HERE,
    )
    t0 = time.time()
    for line in proc.stdout:
        print("  [pid %d] %s" % (proc.pid, line.rstrip()))
        if line.startswith("CHECKPOINT_SAVED"):
            break
    # честный обрыв: SIGKILL не даёт процессу ничего доделать и ничего дописать
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    print(f"процесс {proc.pid} убит сигналом KILL через {round(time.time()-t0,2)} с, "
          f"код возврата {proc.returncode}")

    conn, graph = open_graph()
    state = graph.get_state(CONFIG)
    print("--- что осталось в SQLite после обрыва ---")
    print(f"  notes: {len(state.values.get('notes',''))} симв., "
          f"draft: {len(state.values.get('draft',''))} симв.")
    print(f"  следующий узел: {','.join(state.next) if state.next else 'END'}")
    print(f"  чекпоинтов по thread_id={THREAD_ID}: {len(list(graph.get_state_history(CONFIG)))}")

    print("=== фаза 2: возобновление с того же thread_id ===")
    # None вместо входа означает «продолжай с сохранённого состояния»
    t0 = time.time()
    final = graph.invoke(None, CONFIG, durability="sync")
    print(f"граф доигран за {round(time.time()-t0,2)} с")
    print("--- журнал маршрутизации за оба процесса ---")
    for line in final["trace"]:
        print(" ", line)
    print("--- готовый текст ---")
    print(final["draft"])
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        phase1_worker()
    else:
        phase2_parent()
