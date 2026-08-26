# sentence-transformers 6.0.0, модель cross-encoder/ms-marco-MiniLM-L-6-v2 (CPU)
# прогнано на стенде 2026-08-26; по документации https://sbert.net/docs/cross_encoder/usage/usage.html

from sentence_transformers import CrossEncoder

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_model: CrossEncoder | None = None


def _get_model() -> CrossEncoder:
    global _model
    if _model is None:
        _model = CrossEncoder(_MODEL_NAME)
    return _model


def rerank(query: str, candidates: list[tuple[str, str, float]]):
    """Пересчитывает релевантность пар (запрос, документ) для кандидатов, отобранных
    baseline-поиском. candidates, список (id, текст, baseline_score).
    Возвращает список (id, текст, cross_encoder_score), отсортированный по убыванию
    cross_encoder_score. Скор это сырой логит модели MS MARCO, не нормализован в 0-1,
    важен порядок значений, а не само число."""
    model = _get_model()
    pairs = [(query, text) for _, text, _ in candidates]
    scores = model.predict(pairs)
    reranked = [
        (doc_id, text, float(score))
        for (doc_id, text, _), score in zip(candidates, scores)
    ]
    reranked.sort(key=lambda item: item[2], reverse=True)
    return reranked
