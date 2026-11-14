# ollama 0.40.13, модель nomic-embed-text, bm25s 0.3.16, Python 3.12, прогнано на стенде 2026-11-14
"""Два индекса над одними и теми же текстами чанков и их слияние через RRF.

- векторный: nomic-embed-text, косинусная близость; модель требует префиксы
  search_document: для чанков и search_query: для запросов;
- лексический: BM25 из bm25s, английские стоп-слова и стеммер Snowball;
- гибрид: Reciprocal Rank Fusion, score = сумма 1 / (60 + ранг) по обоим спискам.

Индексы ничего не знают о Contextual Retrieval: им на вход подают либо голые чанки,
либо чанки с дописанным контекстом. Вся разница только в тексте.
"""
import json
import os
import urllib.request

import bm25s
import numpy as np
import Stemmer

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"
RRF_K = 60


def embed(texts, prefix):
    body = {"model": EMBED_MODEL, "input": [prefix + t for t in texts], "keep_alive": "30m"}
    req = urllib.request.Request(f"{OLLAMA}/api/embed", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        vectors = np.array(json.load(r)["embeddings"], dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class HybridIndex:
    def __init__(self, texts):
        self.n = len(texts)
        # векторный индекс: матрица нормированных эмбеддингов
        self.vectors = embed(texts, "search_document: ")
        # лексический индекс BM25
        self.stemmer = Stemmer.Stemmer("english")
        self.bm25 = bm25s.BM25()
        self.bm25.index(bm25s.tokenize(texts, stopwords="en", stemmer=self.stemmer, show_progress=False),
                        show_progress=False)

    def rank_vector(self, query):
        q = embed([query], "search_query: ")[0]
        return list(np.argsort(-(self.vectors @ q)))

    def rank_bm25(self, query):
        tokens = bm25s.tokenize([query], stopwords="en", stemmer=self.stemmer, show_progress=False)
        docs, _ = self.bm25.retrieve(tokens, k=self.n, show_progress=False)
        return [int(i) for i in docs[0]]

    def rank_hybrid(self, query):
        # RRF: место в каждом списке превращается в 1 / (60 + ранг), очки складываются
        score = np.zeros(self.n)
        for ranking in (self.rank_vector(query), self.rank_bm25(query)):
            for rank, idx in enumerate(ranking, start=1):
                score[idx] += 1.0 / (RRF_K + rank)
        return list(np.argsort(-score))

    def rank(self, method, query):
        return {"vector": self.rank_vector, "bm25": self.rank_bm25, "hybrid": self.rank_hybrid}[method](query)
