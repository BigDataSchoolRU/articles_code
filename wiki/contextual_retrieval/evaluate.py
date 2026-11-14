# ollama 0.40.13 (nomic-embed-text), bm25s 0.3.16, Python 3.12, прогнано на стенде 2026-11-14
"""Доля неудачных извлечений до и после контекстуализации.

Неудачное извлечение: эталонного чанка нет в top-k выдачи. Это та же метрика, что у
Anthropic (1 − recall@k), только k маленький, потому что и корпус маленький: 24 чанка.
Сравниваются шесть комбинаций: три способа поиска (вектор, BM25, гибрид RRF) на голых
чанках и на чанках, к которым дописан контекст из contexts.json (его пишет contextualize.py).
"""
import json

from corpus import DOCUMENTS, QUERIES, chunks
from index_search import HybridIndex

KS = (1, 3, 5)
METHODS = ("vector", "bm25", "hybrid")


def evaluate(index, ids):
    fails = {(m, k): 0 for m in METHODS for k in KS}
    tops = {}
    for query, (doc_id, i) in QUERIES:
        gold = ids.index(f"{doc_id}#{i}")
        for m in METHODS:
            ranking = index.rank(m, query)
            tops[(m, query)] = ranking[:3]
            for k in KS:
                if gold not in ranking[:k]:
                    fails[(m, k)] += 1
    return fails, tops


def main():
    ch = chunks()
    ids = [c[0] for c in ch]
    plain = [c[3] for c in ch]
    with open("contexts.json", encoding="utf-8") as f:
        contexts = json.load(f)
    # Contextual Retrieval: контекст дописывается в начало чанка, дальше обычная индексация
    contextual = [contexts[cid]["context"] + "\n\n" + text for cid, text in zip(ids, plain)]

    n = len(QUERIES)
    results = {}
    for name, texts in (("голые чанки", plain), ("чанки с контекстом", contextual)):
        results[name] = evaluate(HybridIndex(texts), ids)

    print(f"чанков: {len(ids)}, запросов: {n}")
    print(f"\nдоля неудачных извлечений (эталона нет в top-k), из {n} запросов")
    print(f"{'поиск':8} {'k':>2} {'голые чанки':>14} {'с контекстом':>14}")
    for m in METHODS:
        for k in KS:
            a = results["голые чанки"][0][(m, k)]
            b = results["чанки с контекстом"][0][(m, k)]
            print(f"{m:8} {k:>2} {a:>3} ({100 * a / n:3.0f}%)    {b:>3} ({100 * b / n:3.0f}%)")

    # Привязал ли контекст чанк к документу: есть ли в нём название компании и квартал из шапки
    anchored = []
    for cid in ids:
        doc_id = cid.split("#")[0]
        company = DOCUMENTS[doc_id][0].split(".")[0]          # «Northwind Logistics»
        quarter = doc_id.split("_")[1].upper() + " 2025"      # «Q1 2025»
        ctx = contexts[cid]["context"]
        if company.split()[0] in ctx and quarter in ctx:
            anchored.append(cid)
        else:
            print(f"контекст без компании или квартала, {cid}: {ctx}")
    print(f"контекстов с названием компании и кварталом: {len(anchored)} из {len(ids)}")

    # Какие запросы гибрид на чанках с контекстом всё ещё промахивает при k=3
    print("\nпромахи гибрида с контекстом при k=3:")
    for query, (doc_id, i) in QUERIES:
        top = results["чанки с контекстом"][1][("hybrid", query)]
        gold = ids.index(f"{doc_id}#{i}")
        if gold not in top:
            print(f"  {query} -> эталон {doc_id}#{i}, top-3: " + ", ".join(ids[j] for j in top))

    # Разбор одного запроса: что гибрид ставит в top-3 до и после
    query, (doc_id, i) = QUERIES[0]
    print(f"\nзапрос: {query}\nэталон: {doc_id}#{i}")
    for name in results:
        top = results[name][1][("hybrid", query)]
        print(f"  {name}, гибрид top-3: " + ", ".join(ids[j] for j in top))


if __name__ == "__main__":
    main()
