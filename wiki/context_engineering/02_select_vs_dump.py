# Python 3.12 stdlib, ollama 0.40.13, модель qwen2.5:7b, прогнано на стенде 2026-11-05
"""Отбор против «всё в окно»: один и тот же вопрос по базе из 36 заметок.

База знаний это 36 коротких заметок дежурного инженера про внутренние сервисы. Ответ на вопрос
лежит ровно в одной из них (иголка), рядом лежит устаревшая заметка с похожими словами.

Режим dump: все 36 заметок идут в окно, иголка ставится в начало, в середину и в конец.
Режим select: окно получает только top-3 заметки по BM25 (написан на stdlib ниже).

Для каждого режима печатается: ответ модели, верен ли он, сколько токенов промпта
модель прочитала (prompt_eval_count) и сколько секунд ушло на их чтение (префилл).
Метка сессии в начале системного промпта меняется на каждом вызове: иначе Ollama возьмёт
общий префикс прошлого вызова из кэша, и время префилла режимов станет несравнимым.
"""
import json
import math
import os
import random
import re
import sys
import time
import urllib.request
import uuid

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
NUM_CTX = 8192

QUESTION = "На каком порту сервис ledger отдаёт метрики Prometheus?"
ANSWER = "9464"
NEEDLE = ("Сервис ledger ведёт проводки по счетам клиентов. Метрики Prometheus он отдаёт "
          "на порту 9464, путь /metrics, скрейп раз в 15 секунд. Владелец: команда finance-core.")
# устаревшая заметка с теми же словами: проверяет, не перепутает ли модель
STALE = ("Сервис ledger_v1 выведен из эксплуатации в 2025 году. Раньше он отдавал метрики "
         "на порту 9100, сейчас этот порт занят node_exporter.")

SERVICES = ["billing", "auth", "catalog", "search", "notify", "orders", "cart", "media",
            "geo", "pricing", "reports", "audit", "gateway", "profile", "chat", "promo",
            "delivery", "stock"]
TEAMS = ["platform", "growth", "core-api", "data", "mobile", "infra"]


def build_notes():
    # 34 заметки-шума по двум шаблонам: про логи и про дежурства, с метриками на своих портах
    rnd = random.Random(7)
    notes = []
    for i, s in enumerate(SERVICES):
        notes.append(f"Сервис {s} пишет логи в /var/log/{s} и хранит их {rnd.randint(3, 30)} дней. "
                     f"Метрики сервиса {s} доступны на порту {9200 + i * 7}. "
                     f"Владелец: команда {rnd.choice(TEAMS)}.")
        if len(notes) < 34:
            notes.append(f"Дежурство по сервису {s} передаётся по понедельникам в 10:00. "
                         f"При падении {s} сначала проверьте очередь {s}_events и пул соединений "
                         f"к базе, лимит {rnd.choice([20, 50, 100])} соединений.")
    notes = notes[:34] + [STALE]
    rnd.shuffle(notes)
    return notes


def tokens(text):
    # грубый стеммер: слово режется до первых 5 символов, чтобы «порту» совпало с «порт»
    return [w[:5] for w in re.findall(r"\w+", text.lower())]


def bm25_top(query, docs, k=3, k1=1.5, b=0.75):
    # классический BM25 без внешних библиотек
    docs_t = [tokens(d) for d in docs]
    avgdl = sum(map(len, docs_t)) / len(docs_t)
    n = len(docs_t)
    scores = []
    for i, dt in enumerate(docs_t):
        s = 0.0
        for q in set(tokens(query)):
            df = sum(1 for d in docs_t if q in d)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            tf = dt.count(q)
            s += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(dt) / avgdl))
        scores.append((s, i))
    return [docs[i] for _, i in sorted(scores, reverse=True)[:k]]


def ask(notes):
    # системный промпт одинаковый, меняется только набор заметок в окне
    ctx = "\n".join(f"[{i + 1}] {n}" for i, n in enumerate(notes))
    messages = [
        {"role": "system", "content": f"[сессия {uuid.uuid4().hex[:8]}] Ты помощник дежурного инженера. Отвечай только по заметкам. "
                                      "Если ответа в заметках нет, ответь: нет данных."},
        {"role": "user", "content": f"Заметки:\n{ctx}\n\nВопрос: {QUESTION}\nОтветь одним числом."},
    ]
    body = {"model": MODEL, "messages": messages, "stream": False, "keep_alive": "60m",
            "options": {"temperature": 0, "seed": 42, "num_ctx": NUM_CTX, "num_predict": 20}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as resp:
        return json.load(resp)


def report(label, notes):
    t = time.time()
    r = ask(notes)
    answer = r["message"]["content"].strip().replace("\n", " ")
    ok = ANSWER in answer
    print(f"{label:<16} заметок {len(notes):>2}  токенов промпта {r['prompt_eval_count']:>5}  "
          f"префилл {r['prompt_eval_duration'] / 1e9:6.1f} с  всего {time.time() - t:6.1f} с  "
          f"верно {'да ' if ok else 'нет'}  ответ: {answer[:60]}")
    return ok


def main():
    base = build_notes()
    print(f"модель {MODEL}, num_ctx {NUM_CTX}, заметок в базе {len(base) + 1}")
    # dump: вся база в окне, иголка в трёх позициях
    for label, pos in [("dump, начало", 0), ("dump, середина", len(base) // 2), ("dump, конец", len(base))]:
        notes = base[:pos] + [NEEDLE] + base[pos:]
        report(label, notes)
    # select: в окно идут только три лучшие заметки по BM25
    top = bm25_top(QUESTION, base + [NEEDLE], k=3)
    print("BM25 top-3:", " | ".join(n[:45] + "..." for n in top))
    report("select, top-3", top)


if __name__ == "__main__":
    main()
