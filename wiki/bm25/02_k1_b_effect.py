# bm25s 0.3.16 (method="lucene"), numpy 2.5.4, Python 3.12.3, прогнано на стенде 2026-11-13
"""Как k1 и b меняют выдачу BM25.

k1 отвечает за насыщение: насколько десятое повторение слова весит меньше первого.
b отвечает за длину: насколько длинный документ штрафуется за то, что слов в нем больше.
"""
from collections import Counter

import bm25s
import numpy as np

from corpus import TEXTS, short, tokenize

corpus_tokens = [tokenize(t) for t in TEXTS]
doc_len = np.array([len(d) for d in corpus_tokens])
avgdl = doc_len.mean()
QUERY = ["индекс"]

# 1. Насыщение частоты при |D| = avgdl: формула Lucene, без множителя (k1 + 1)
print("=== 1. Частотная часть tf / (tf + k1) при |D| = avgdl, предел 1.0 ===")
tfs = [1, 2, 3, 5, 10, 20]
print(f"{'':<12}" + "".join(f"{'tf=' + str(t):>9}" for t in tfs))
for k1 in (0.5, 1.2, 2.0):
    print(f"{'k1=' + str(k1):<12}" + "".join(f"{t / (t + k1):>9.3f}" for t in tfs))
print(f"{'TF-IDF':<12}" + "".join(f"{t:>9}" for t in tfs) + "   (линейно, без предела)")

# 2. Документы со словом «индекс»: частота и длина
hits = [d for d, toks in enumerate(corpus_tokens) if "индекс" in toks]
print(f"\n=== 2. Документы со словом «индекс», avgdl={avgdl:.2f} ===")
for d in hits:
    print(f"{short(d)} tf={Counter(corpus_tokens[d])['индекс']:<3} |D|={doc_len[d]:<4} |D|/avgdl={doc_len[d] / avgdl:.2f}")

# 3. Сетка k1 x b: оценки и порядок
print("\n=== 3. Сетка k1 x b, запрос «индекс», порядок документов и оценки ===")
for k1 in (0.5, 1.2, 2.0):
    for b in (0.0, 0.75, 1.0):
        model = bm25s.BM25(method="lucene", k1=k1, b=b)
        model.index(corpus_tokens, show_progress=False)
        s = model.get_scores(QUERY)
        order = sorted(hits, key=lambda d: -s[d])
        row = "  ".join(f"d{d}:{s[d]:.3f}" for d in order)
        print(f"k1={k1:<4} b={b:<5} {row}")
