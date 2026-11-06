# hnswlib 0.8.0, faiss-cpu 1.15.1, numpy 2.5.4, Python 3.12.3, прогнано на стенде 2026-11-06
"""Демо HNSW: уровни графа, компромисс efSearch, цена M, фильтрация и удаления.

Запуск: python hnsw_demo.py all|levels|ef_sweep|m_sweep|filter|delete
Сборка индекса идёт в BUILD_THREADS потоков, поиск всегда в один поток,
чтобы латентность запроса не зависела от числа ядер.
"""
import os
import sys
import tempfile
import time
from collections import Counter

import faiss
import hnswlib
import numpy as np

import data

BUILD_THREADS = 4
K = data.K


def build_hnswlib(base, M=16, ef_construction=200, allow_replace_deleted=False):
    """Строит индекс hnswlib и возвращает его вместе со временем сборки в секундах."""
    index = hnswlib.Index(space="l2", dim=base.shape[1])
    index.init_index(max_elements=len(base), M=M, ef_construction=ef_construction,
                     random_seed=100, allow_replace_deleted=allow_replace_deleted)
    t0 = time.perf_counter()
    index.add_items(base, np.arange(len(base)), num_threads=BUILD_THREADS)
    return index, time.perf_counter() - t0


def timed_query(index, queries, k=K, **kwargs):
    """Поиск в один поток: метки и средняя латентность одного запроса в миллисекундах."""
    t0 = time.perf_counter()
    labels, _ = index.knn_query(queries, k=k, num_threads=1, **kwargs)
    return labels, (time.perf_counter() - t0) / len(queries) * 1e3


def file_size_mb(index):
    """Размер индекса на диске после save_index, в мегабайтах."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "index.bin")
        index.save_index(path)
        return os.path.getsize(path) / 2**20


def levels(d):
    """FAISS IndexHNSWFlat: сколько векторов живёт на каждом слое и сколько расстояний считает поиск."""
    M = 16
    base, queries, gt = d["base"], d["queries"], d["gt"]
    index = faiss.IndexHNSWFlat(data.DIM, M)
    index.hnsw.efConstruction = 200
    faiss.omp_set_num_threads(BUILD_THREADS)
    t0 = time.perf_counter()
    index.add(base)
    print(f"IndexHNSWFlat M={M}, efConstruction=200: {index.ntotal} векторов за "
          f"{time.perf_counter() - t0:.1f} с")
    hnsw = index.hnsw
    print(f"соседей на слое 0: {hnsw.nb_neighbors(0)}, на слоях выше: {hnsw.nb_neighbors(1)}")

    # levels хранит для каждого вектора число слоёв, в которых он есть: верхний слой плюс один
    top_layer = faiss.vector_to_array(hnsw.levels) - 1
    counts = Counter(top_layer.tolist())
    probas = faiss.vector_to_array(hnsw.assign_probas)
    print(f"верхний слой графа max_level = {hnsw.max_level}, "
          f"точка входа: вектор {hnsw.entry_point}, его верхний слой {top_layer[hnsw.entry_point]}")
    print("верхний слой | векторов | доля     | ожидание (1-1/M)*M^-l | есть на слое (снизу вверх)")
    present = len(top_layer)
    for layer in range(hnsw.max_level + 1):
        n = counts.get(layer, 0)
        expected = probas[layer] * len(top_layer) if layer < len(probas) else 0.0
        print(f"{layer:12d} | {n:8d} | {n / len(top_layer):8.5f} | {expected:21.1f} | {present}")
        present -= n

    # сколько расстояний реально считает поиск: счётчик FAISS по всем запросам
    faiss.omp_set_num_threads(1)
    print("efSearch | recall@10 | расстояний на запрос | доля базы | мс/запрос")
    for ef in (16, 40, 160):
        hnsw.efSearch = ef
        faiss.cvar.hnsw_stats.reset()
        t0 = time.perf_counter()
        _, found = index.search(queries, K)
        ms = (time.perf_counter() - t0) / len(queries) * 1e3
        ndis = faiss.cvar.hnsw_stats.ndis / len(queries)
        print(f"{ef:8d} | {data.recall_at_k(found, gt):9.4f} | {ndis:20.0f} | "
              f"{ndis / len(base):9.4f} | {ms:.3f}")


def ef_sweep(d):
    """hnswlib M=16: recall@10 и латентность при росте ef, рядом точный перебор."""
    base, queries, gt = d["base"], d["queries"], d["gt"]
    index, build_s = build_hnswlib(base, M=16, ef_construction=200)
    print(f"hnswlib M=16, ef_construction=200: сборка {build_s:.1f} с в {BUILD_THREADS} потока")

    # эталон скорости: точный перебор FAISS IndexFlatL2, по одному запросу в один поток
    faiss.omp_set_num_threads(1)
    flat = faiss.IndexFlatL2(data.DIM)
    flat.add(base)
    t0 = time.perf_counter()
    for q in queries:
        flat.search(q[None, :], K)
    flat_ms = (time.perf_counter() - t0) / len(queries) * 1e3
    print(f"точный перебор IndexFlatL2: recall@10 = 1.0000, {flat_ms:.3f} мс/запрос")

    print("ef  | recall@10 | мс/запрос | быстрее перебора")
    for ef in (10, 20, 40, 80, 160, 320):
        index.set_ef(ef)
        labels, ms = timed_query(index, queries)
        print(f"{ef:3d} | {data.recall_at_k(labels, gt):9.4f} | {ms:9.3f} | {flat_ms / ms:6.1f}x")


def m_sweep(d):
    """Цена M: время сборки, размер индекса и recall при фиксированных ef_construction и ef."""
    base, queries, gt = d["base"], d["queries"], d["gt"]
    raw_mb = base.nbytes / 2**20
    print(f"сырые векторы float32: {raw_mb:.1f} МБ; ef_construction=200, ef=40")
    print("M  | сборка, с | индекс, МБ | сверх векторов, МБ | recall@10 | мс/запрос")
    for M in (4, 8, 16, 32, 64):
        index, build_s = build_hnswlib(base, M=M, ef_construction=200)
        index.set_ef(40)
        labels, ms = timed_query(index, queries)
        size = file_size_mb(index)
        print(f"{M:2d} | {build_s:9.1f} | {size:10.1f} | {size - raw_mb:18.1f} | "
              f"{data.recall_at_k(labels, gt):9.4f} | {ms:.3f}")
        del index


def filter_demo(d):
    """Фильтр около 1%: отбор после поиска против фильтра внутри обхода графа."""
    base, queries, category = d["base"], d["queries"], d["category"]
    allowed_ids = np.flatnonzero(category == 0)
    allowed = set(allowed_ids.tolist())
    print(f"фильтр category == 0: подходит {len(allowed_ids)} из {len(base)} "
          f"({len(allowed_ids) / len(base):.2%})")
    # эталон для фильтра: точный перебор только среди подходящих векторов
    gt_f = data.exact_knn(base, queries, K, subset=allowed_ids)
    index, _ = build_hnswlib(base, M=16, ef_construction=200)

    print("стратегия                         | ef   | строк из 10, среднее | запросов с 10 | recall@10 | мс/запрос")
    # отбор после поиска: индекс отдаёт ef кандидатов, фильтр выкидывает неподходящие
    for ef in (40, 400, 2000):
        index.set_ef(ef)
        labels, ms = timed_query(index, queries, k=ef)
        rows = [[i for i in row if i in allowed][:K] for row in labels]
        got = np.array([len(r) for r in rows])
        rec = np.mean([len(set(r) & set(t)) / K for r, t in zip(rows, gt_f)])
        print(f"после поиска, взять ef кандидатов  | {ef:4d} | {got.mean():20.2f} | "
              f"{(got == K).sum():13d} | {rec:9.4f} | {ms:.3f}")
    # фильтр внутри обхода: hnswlib проверяет условие на каждом кандидате и идёт дальше
    for ef in (40, 400):
        index.set_ef(ef)
        labels, ms = timed_query(index, queries, filter=allowed.__contains__)
        got = np.array([len(row) for row in labels])
        print(f"внутри обхода (filter=)           | {ef:4d} | {got.mean():20.2f} | "
              f"{(got == K).sum():13d} | {data.recall_at_k(labels, gt_f):9.4f} | {ms:.3f}")
    # предфильтр: точный перебор только по подходящим векторам, без графа
    faiss.omp_set_num_threads(1)
    flat = faiss.IndexFlatL2(data.DIM)
    flat.add(base[allowed_ids])
    t0 = time.perf_counter()
    found = [allowed_ids[flat.search(q[None, :], K)[1][0]] for q in queries]
    ms = (time.perf_counter() - t0) / len(queries) * 1e3
    print(f"предфильтр: перебор {len(allowed_ids)} подходящих | —    | {K:20.2f} | "
          f"{len(queries):13d} | {data.recall_at_k(found, gt_f):9.4f} | {ms:.3f}")

    # сколько стоит сам колбэк Python: фильтр, который пропускает всё, против поиска без фильтра
    index.set_ef(40)
    _, plain_ms = timed_query(index, queries)
    _, cb_ms = timed_query(index, queries, filter=lambda label: True)
    print(f"цена колбэка при ef=40: без фильтра {plain_ms:.3f} мс, "
          f"filter=lambda: True {cb_ms:.3f} мс на запрос")


def delete_demo(d):
    """Удаление пометкой: помеченные не возвращаются, место в индексе не освобождается."""
    base, queries = d["base"], d["queries"]
    index, _ = build_hnswlib(base, M=16, ef_construction=200, allow_replace_deleted=True)
    index.set_ef(40)
    size_before = file_size_mb(index)
    deleted = np.arange(0, len(base), 10)          # каждый десятый вектор, 10%
    for label in deleted:
        index.mark_deleted(int(label))
    deleted_set = set(deleted.tolist())
    labels, _ = timed_query(index, queries)
    leaked = sum(1 for row in labels for i in row if i in deleted_set)
    alive = np.setdiff1d(np.arange(len(base)), deleted)
    gt_alive = data.exact_knn(base, queries, K, subset=alive)
    print(f"помечено удалёнными: {len(deleted)}; удалённых в выдаче: {leaked} из {labels.size}")
    print(f"recall@10 по живым векторам: {data.recall_at_k(labels, gt_alive):.4f}")
    print(f"элементов в индексе: {index.get_current_count()}, размер {size_before:.1f} -> "
          f"{file_size_mb(index):.1f} МБ")
    # новые векторы занимают слоты помеченных, индекс не растёт
    rng = np.random.default_rng(7)
    fresh = base[rng.choice(alive, size=len(deleted))] + 0.01
    index.add_items(fresh, np.arange(len(base), len(base) + len(fresh)), num_threads=BUILD_THREADS,
                    replace_deleted=True)
    print(f"после add_items(replace_deleted=True) на {len(fresh)} новых: элементов "
          f"{index.get_current_count()}, max_elements {index.get_max_elements()}, "
          f"размер {file_size_mb(index):.1f} МБ")


SCENARIOS = {"levels": levels, "ef_sweep": ef_sweep, "m_sweep": m_sweep,
             "filter": filter_demo, "delete": delete_demo}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode != "all" and mode not in SCENARIOS:
        sys.exit(f"режим: all|{'|'.join(SCENARIOS)}")
    dataset = data.load()
    print(f"данные: {data.N} векторов, {data.DIM} измерений, {data.N_QUERIES} запросов, seed {data.SEED}")
    for name, func in SCENARIOS.items():
        if mode in ("all", name):
            print(f"\n===== {name} =====")
            t0 = time.perf_counter()
            func(dataset)
            print(f"--- {name}: {time.perf_counter() - t0:.1f} с")
