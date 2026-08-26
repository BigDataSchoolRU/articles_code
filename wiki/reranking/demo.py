# связывает retrieve.py (baseline) и rerank.py (cross-encoder), прогнано на стенде 2026-08-26

import time

from corpus import DOCUMENTS, QUERY
from retrieve import baseline_retrieve
from rerank import rerank

TOP_N = 5  # сколько кандидатов baseline-поиск отдаёт reranker'у


def main():
    print(f"Запрос: {QUERY}\n")

    t0 = time.time()
    baseline = baseline_retrieve(QUERY, DOCUMENTS, TOP_N)
    baseline_time = time.time() - t0

    print(f"=== Baseline: top-{TOP_N} по косинусному сходству эмбеддингов ({baseline_time:.2f} с) ===")
    for rank, (doc_id, text, score) in enumerate(baseline, start=1):
        print(f"{rank}. [{doc_id}] cosine={score:.4f}")
        print(f"   {text}")

    t0 = time.time()
    reranked = rerank(QUERY, baseline)
    rerank_time = time.time() - t0

    print(f"\n=== После reranking cross-encoder'ом ({rerank_time:.2f} с на {TOP_N} пар) ===")
    for rank, (doc_id, text, score) in enumerate(reranked, start=1):
        print(f"{rank}. [{doc_id}] cross_encoder_score={score:.4f}")
        print(f"   {text}")

    baseline_order = [doc_id for doc_id, _, _ in baseline]
    reranked_order = [doc_id for doc_id, _, _ in reranked]
    print(f"\nПорядок baseline: {baseline_order}")
    print(f"Порядок после reranking: {reranked_order}")
    print(f"Порядок изменился: {baseline_order != reranked_order}")


if __name__ == "__main__":
    main()
