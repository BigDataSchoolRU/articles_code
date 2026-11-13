# bm25s 0.3.16, PyStemmer 3.1.0 (Snowball russian), Python 3.12.3, прогнано на стенде 2026-11-13
"""BM25 на русском тексте без стемминга и со стеммингом.

BM25 сравнивает токены побуквенно. «индекс», «индекса» и «индексом» для него три разных
слова, пока анализатор не приведет их к одной основе.
"""
import bm25s
import numpy as np
import Stemmer

from corpus import QUERIES, TEXTS, short

stemmer = Stemmer.Stemmer("russian")

print("=== 1. Что делает стеммер Snowball russian ===")
for group in (["индекс", "индекса", "индексу", "индексом", "индексы", "индексами"],
              ["ускоряет", "ускоряют", "ускорить"],
              ["данные", "данных", "данным"],
              ["поиск", "поиска", "поисковике"]):
    print("  ".join(f"{w}->{stemmer.stemWord(w)}" for w in group))


def build(stem):
    """Индекс bm25s: русские стоп-слова встроены в bm25s, стеммер опционален."""
    toks = bm25s.tokenize(TEXTS, stopwords="ru", stemmer=stem,
                          return_ids=False, show_progress=False)
    model = bm25s.BM25(method="lucene", k1=1.2, b=0.75)
    model.index(toks, show_progress=False)
    return model


def search(model, stem, text, k=5):
    q = bm25s.tokenize(text, stopwords="ru", stemmer=stem,
                       return_ids=False, show_progress=False)[0]
    known = [w for w in q if w in model.vocab_dict]
    scores = model.get_scores(known) if known else np.zeros(len(TEXTS))
    top = [int(d) for d in np.argsort(-scores, kind="stable")[:k] if scores[d] > 0]
    return q, known, [(d, float(scores[d])) for d in top]


plain, stemmed = build(None), build(stemmer)
print(f"\nСловарь индекса: без стемминга {len(plain.vocab_dict)} токенов, со стеммингом {len(stemmed.vocab_dict)}")

for key in ("q3", "q1"):
    text = QUERIES[key]
    print(f"\n=== 2. Запрос «{text}» ===")
    for name, model, stem in (("без стемминга", plain, None), ("Snowball russian", stemmed, stemmer)):
        q, known, top = search(model, stem, text)
        print(f"{name}: токены запроса {q}, найдены в словаре {known}")
        if not top:
            print("   ничего не найдено")
        for d, s in top:
            print(f"   {short(d)} {s:.3f}")
