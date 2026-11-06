# numpy 2.5.4, Python 3.12.3, прогнано на стенде 2026-11-06
"""Синтетические данные и эталон для демо HNSW.

Векторы берутся из смеси гауссовых кластеров, а не из равномерного шума: равномерный шум в
128 измерениях это худший случай для любого графового индекса и на эмбеддинги не похож.
Кластеры живут в пространстве из LATENT измерений и линейно разворачиваются в DIM с небольшим
шумом: у реальных эмбеддингов внутренняя размерность тоже заметно меньше номинальной.
Эталон считается точным перебором, по нему меряется recall приближённого поиска.
Результат кэшируется в data_cache.npz рядом с файлом, повторный запуск берёт кэш.
"""
from pathlib import Path
import time

import numpy as np

N = 100_000          # векторов в индексе
DIM = 128            # размерность
N_QUERIES = 1_000    # запросов
N_CLUSTERS = 200     # кластеров в смеси
LATENT = 32          # внутренняя размерность данных
N_CATEGORIES = 100   # значения атрибута для фильтра: одна категория это около 1% векторов
K = 10               # сколько соседей ищем
SEED = 42
CACHE = Path(__file__).resolve().parent / "data_cache.npz"


def _mixture(rng, centers, proj, n):
    """n точек: случайный центр плюс шум в латентном пространстве, проекция в DIM и шум сверху."""
    labels = rng.integers(0, len(centers), size=n)
    latent = centers[labels] + rng.normal(0.0, 1.0, size=(n, LATENT))
    points = latent @ proj + rng.normal(0.0, 0.1, size=(n, DIM))
    return points.astype(np.float32)


def exact_knn(base, queries, k, subset=None, chunk=100):
    """Точный kNN полным перебором по квадрату L2. subset ограничивает поиск номерами векторов."""
    ids = np.arange(len(base)) if subset is None else np.asarray(subset)
    vectors = base[ids]
    norms = (vectors ** 2).sum(axis=1)
    result = np.empty((len(queries), k), dtype=np.int64)
    for start in range(0, len(queries), chunk):
        q = queries[start:start + chunk]
        # |q - x|^2 = |q|^2 - 2 q·x + |x|^2, слагаемое |q|^2 на порядок не влияет
        dist = norms[None, :] - 2.0 * q @ vectors.T
        top = np.argpartition(dist, k, axis=1)[:, :k]
        order = np.take_along_axis(dist, top, axis=1).argsort(axis=1)
        result[start:start + chunk] = ids[np.take_along_axis(top, order, axis=1)]
    return result


def load():
    """Возвращает словарь: base, queries, category, gt (эталон top-K на всей базе)."""
    if CACHE.exists():
        data = np.load(CACHE)
        return {name: data[name] for name in data.files}
    rng = np.random.default_rng(SEED)
    # центры разнесены так, что соседние кластеры частично перекрываются
    centers = rng.normal(0.0, 1.0, size=(N_CLUSTERS, LATENT))
    proj = rng.normal(0.0, 1.0 / np.sqrt(LATENT), size=(LATENT, DIM))
    base = _mixture(rng, centers, proj, N)
    queries = _mixture(rng, centers, proj, N_QUERIES)
    # атрибут для фильтра не связан с геометрией: соседи по вектору не обязаны совпадать по категории
    category = rng.integers(0, N_CATEGORIES, size=N).astype(np.int32)
    t0 = time.perf_counter()
    gt = exact_knn(base, queries, K)
    print(f"эталон точным перебором numpy: {N_QUERIES} запросов по {N} векторов "
          f"за {time.perf_counter() - t0:.1f} с")
    np.savez(CACHE, base=base, queries=queries, category=category, gt=gt)
    return {"base": base, "queries": queries, "category": category, "gt": gt}


def recall_at_k(found, truth):
    """Средняя доля истинных K соседей, которые нашёл приближённый поиск."""
    hits = [len(set(f) & set(t)) / len(t) for f, t in zip(found, truth)]
    return float(np.mean(hits))


if __name__ == "__main__":
    d = load()
    print({name: arr.shape for name, arr in d.items()})
