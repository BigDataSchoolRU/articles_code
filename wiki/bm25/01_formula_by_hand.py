# rank-bm25 0.2.2, bm25s 0.3.16, numpy 2.5.4, Python 3.12.3, прогнано на стенде 2026-11-13
"""BM25 руками по формуле и сверка с rank-bm25 и bm25s на одной токенизации.

Оценка документа D по запросу Q это сумма по словам запроса:
    IDF(q) * tf(q, D) * [k1 + 1] / (tf(q, D) + k1 * (1 - b + b * |D| / avgdl))
Библиотеки расходятся в двух местах: как считать IDF и есть ли множитель (k1 + 1).
"""
import inspect
import math
from collections import Counter

import bm25s
import numpy as np
import rank_bm25

from corpus import QUERIES, TEXTS, short, tokenize

K1, B = 1.2, 0.75  # умолчания Lucene и Elasticsearch

corpus_tokens = [tokenize(t) for t in TEXTS]
N = len(corpus_tokens)
doc_len = [len(d) for d in corpus_tokens]
avgdl = sum(doc_len) / N
tf = [Counter(d) for d in corpus_tokens]
df = Counter(w for d in corpus_tokens for w in set(d))


# ── три формулы IDF ──────────────────────────────────────────────────────
def idf_robertson(n: int) -> float:
    """Классика Робертсона: у слова из больше чем половины документов уходит в минус."""
    return math.log((N - n + 0.5) / (n + 0.5))


def idf_lucene(n: int) -> float:
    """Lucene и Elasticsearch: единица под логарифмом, IDF всегда больше нуля."""
    return math.log(1 + (N - n + 0.5) / (n + 0.5))


# rank-bm25 подменяет отрицательный IDF на epsilon * средний IDF по словарю
ROB = {w: idf_robertson(n) for w, n in df.items()}
EPS_FLOOR = 0.25 * (sum(ROB.values()) / len(ROB))


def idf_rank_bm25(n_word: str) -> float:
    v = ROB[n_word]
    return v if v >= 0 else EPS_FLOOR


def idf_bm25s_robertson(n: int) -> float:
    """bm25s, method='robertson': отрицательный IDF обрезается до нуля."""
    return math.log(max((N - n + 0.5) / (n + 0.5), 1.0))


# ── частотная часть ─────────────────────────────────────────────────────
def tf_part(f: int, dl: int, k1: float, b: float, plus1: bool) -> float:
    norm = k1 * (1 - b + b * dl / avgdl)
    return f * ((k1 + 1) if plus1 else 1) / (f + norm)


def score(query: list[str], d: int, idf, plus1: bool) -> float:
    s = 0.0
    for q in query:
        f = tf[d].get(q, 0)
        if f:
            s += idf(q) * tf_part(f, doc_len[d], K1, B, plus1)
    return s


VARIANTS = {
    # имя: (IDF по слову, множитель k1+1)
    "rank-bm25 BM25Okapi": (idf_rank_bm25, True),
    "bm25s lucene": (lambda w: idf_lucene(df[w]), False),
    "bm25s robertson": (lambda w: idf_bm25s_robertson(df[w]), False),
}

# ── библиотеки на тех же токенах ────────────────────────────────────────
okapi = rank_bm25.BM25Okapi(corpus_tokens, k1=K1, b=B, epsilon=0.25)
lib_lucene = bm25s.BM25(method="lucene", k1=K1, b=B)
lib_lucene.index(corpus_tokens, show_progress=False)
lib_rob = bm25s.BM25(method="robertson", k1=K1, b=B)
lib_rob.index(corpus_tokens, show_progress=False)


def lib_scores(name: str, q: list[str]) -> np.ndarray:
    if name == "rank-bm25 BM25Okapi":
        return np.asarray(okapi.get_scores(q))
    lib = lib_lucene if name == "bm25s lucene" else lib_rob
    known = [w for w in q if w in df]  # bm25s молча выкидывает слова вне словаря
    return lib.get_scores(known).astype(float) if known else np.zeros(N)



print("Умолчания библиотек (inspect.signature):")
print(f"  rank_bm25.BM25Okapi{inspect.signature(rank_bm25.BM25Okapi.__init__)}")
sig = inspect.signature(bm25s.BM25.__init__).parameters
print(f"  bm25s.BM25: k1={sig['k1'].default}, b={sig['b'].default}, method={sig['method'].default!r}")
print(f"Корпус: N={N} документов, avgdl={avgdl:.3f} токена, словарь {len(df)} слов")
print(f"k1={K1}, b={B}; floor rank-bm25 для отрицательного IDF = 0.25 * средний IDF = {EPS_FLOOR:.4f}")

# 1. Сверка «руками против библиотек»: максимальное расхождение по всем запросам и документам
print("\n=== 1. Формула руками против библиотек, max |разница| по 4 запросам x 16 документам ===")
for name, (idf, plus1) in VARIANTS.items():
    worst = 0.0
    for qtext in QUERIES.values():
        q = tokenize(qtext)
        hand = np.array([score(q, d, idf, plus1) for d in range(N)])
        worst = max(worst, float(np.max(np.abs(hand - lib_scores(name, q)))))
    print(f"{name:<22} {worst:.2e}")

# 2. Разбор одной оценки по словам: что именно складывается
q = tokenize(QUERIES["q1"])
best = int(np.argmax([score(q, d, VARIANTS['bm25s lucene'][0], False) for d in range(N)]))
print(f"\n=== 2. Разбор оценки Lucene: запрос «{QUERIES['q1']}», документ {short(best).strip()} ===")
print(f"|D|={doc_len[best]}, |D|/avgdl={doc_len[best] / avgdl:.3f}")
print(f"{'слово':<18}{'tf':>4}{'df':>4}{'IDF':>8}{'tf-часть':>10}{'вклад':>9}")
total = 0.0
for w in q:
    f = tf[best].get(w, 0)
    i = idf_lucene(df[w]) if w in df else 0.0
    part = tf_part(f, doc_len[best], K1, B, False) if f else 0.0
    total += i * part
    print(f"{w:<18}{f:>4}{df.get(w, 0):>4}{i:>8.4f}{part:>10.4f}{i * part:>9.4f}")
print(f"{'итого':<18}{'':>26}{total:>9.4f}   bm25s: {lib_scores('bm25s lucene', q)[best]:.4f}")

# 3. Одинаковые данные, разные числа, сравниваем порядок
for key in ("q1", "q4"):
    q = tokenize(QUERIES[key])
    print(f"\n=== 3. Топ-5 по запросу «{QUERIES[key]}» ===")
    for w in q:
        print(f"   слово «{w}»: df={df.get(w, 0)}, IDF Робертсона={idf_robertson(df[w]) if w in df else float('nan'):+.4f},"
              f" IDF Lucene={idf_lucene(df[w]) if w in df else float('nan'):.4f}")
    for name in VARIANTS:
        s = lib_scores(name, q)
        top = np.argsort(-s, kind="stable")[:5]
        row = "  ".join(f"d{int(d)}:{s[d]:.3f}" for d in top)
        print(f"{name:<22} {row}")
