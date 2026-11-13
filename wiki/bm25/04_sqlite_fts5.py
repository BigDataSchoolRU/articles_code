# SQLite 3.45.1 (модуль sqlite3 из stdlib Python 3.12.3), формула bm25() по ext/fts5/fts5_aux.c, прогнано на стенде 2026-11-13
"""BM25 внутри SQLite FTS5: знак, сверка с формулой и веса колонок.

Функция bm25() в FTS5 считает классический BM25 с IDF Робертсона, k1=1.2 и b=0.75
зашиты в код. Неположительный IDF заменяется на 1e-6. Результат умножается на -1,
чтобы ORDER BY по возрастанию ставил лучшее совпадение первым.
"""
import math
import sqlite3
from collections import Counter

from corpus import DOCS, QUERIES, short, tokenize

con = sqlite3.connect(":memory:")
print(f"SQLite {sqlite3.sqlite_version}")
# две колонки: заголовок и текст; токенизатор unicode61 по умолчанию
con.execute("CREATE VIRTUAL TABLE docs USING fts5(title, body)")
con.executemany("INSERT INTO docs(rowid, title, body) VALUES (?, ?, ?)",
                [(i, t, b) for i, (t, b) in enumerate(DOCS)])


def fts_query(text: str) -> str:
    """В FTS5 слова через пробел означают AND. BM25 ранжирует по любому слову, поэтому OR."""
    return " OR ".join(f'"{w}"' for w in tokenize(text))


# формула bm25() из fts5_aux.c на Python, длина документа по обеим колонкам
toks = [tokenize(t) + tokenize(b) for t, b in DOCS]
title_toks = [Counter(tokenize(t)) for t, _ in DOCS]
body_toks = [Counter(tokenize(b)) for _, b in DOCS]
N = len(toks)
avgdl = sum(len(t) for t in toks) / N
df = Counter(w for t in toks for w in set(t))


def fts5_formula(query: list[str], d: int, w_title=1.0, w_body=1.0) -> float:
    k1, b = 1.2, 0.75
    s = 0.0
    for q in query:
        idf = math.log((N - df[q] + 0.5) / (df[q] + 0.5)) if df[q] else 0.0
        if idf <= 0:
            idf = 1e-6
        f = w_title * title_toks[d][q] + w_body * body_toks[d][q]
        s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(toks[d]) / avgdl))
    return -s


for key in ("q1", "q2", "q4"):
    text = QUERIES[key]
    q = tokenize(text)
    print(f"\n=== Запрос «{text}», MATCH '{fts_query(text)}' ===")
    rows = con.execute(
        "SELECT rowid, bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT 5",
        (fts_query(text),)).fetchall()
    for rowid, sc in rows:
        hand = fts5_formula(q, rowid)
        print(f"{short(rowid)} bm25()={sc:+.6f}  формула={hand:+.6f}  разница={abs(sc - hand):.1e}")

# пробел без OR: только документы, где есть все слова
q1 = QUERIES["q1"]
n_and = con.execute("SELECT count(*) FROM docs WHERE docs MATCH ?",
                    (" ".join(f'"{w}"' for w in tokenize(q1)),)).fetchone()[0]
n_or = con.execute("SELECT count(*) FROM docs WHERE docs MATCH ?", (fts_query(q1),)).fetchone()[0]
print(f"\nЗапрос «{q1}»: через пробел (AND) найдено {n_and} документов, через OR {n_or}")

# rank это bm25() без весов, ORDER BY rank дает тот же порядок
same = con.execute(
    "SELECT count(*) FROM docs WHERE docs MATCH ? AND rank = bm25(docs)", (fts_query(q1),)).fetchone()[0]
print(f"rank = bm25(docs) в {same} строках из {n_or}")

# веса колонок: попадание в заголовок весит как 10 попаданий в текст
q = "индекс"
print(f"\n=== Веса колонок, запрос «{q}»: bm25(docs) против bm25(docs, 10.0, 1.0) ===")
for weights in ((1.0, 1.0), (10.0, 1.0)):
    rows = con.execute(
        "SELECT rowid, bm25(docs, ?, ?) FROM docs WHERE docs MATCH ? ORDER BY 2 LIMIT 5",
        (*weights, f'"{q}"')).fetchall()
    order = "  ".join(f"d{r}:{s:+.3f}" for r, s in rows)
    check = max(abs(s - fts5_formula([q], r, *weights)) for r, s in rows)
    print(f"веса title={weights[0]:<4} body={weights[1]:<4} {order}   max |bm25()-формула|={check:.1e}")
for d in (0, 2, 11):
    print(f"   {short(d)} в заголовке {title_toks[d]['индекс']}, в тексте {body_toks[d]['индекс']}, |D|={len(toks[d])}")
