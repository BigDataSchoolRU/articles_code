# ollama 0.6.2, модели qwen2.5:7b (кандидат), llama3.1:8b (судья), nomic-embed-text (эмбеддинги), прогнано на стенде 2026-08-30
"""
Минимальный харнесс оценки LLM: три независимых слоя метрик на одном наборе вопросов.

Цикл конфигурация -> прогон -> грейдинг -> отчёт:
  1. конфигурация — dataset.jsonl: вопрос, эталонный ответ, критерии
  2. прогон — кандидатная модель генерирует ответ на каждый вопрос
  3. грейдинг — три слоя оценивают один и тот же ответ независимо друг от друга:
       a) детерминированный автотест (подстроки, длина) — быстро и без модели, но грубо
       b) эмбеддинг-сходство с эталоном — ловит смысловую близость, не ловит фактические ошибки
       c) модель-судья (отдельная от кандидата, чтобы не проверять модель её же собственным
          мнением о себе — self-preference bias разобран отдельно в статье про LLM-as-a-Judge)
  4. отчёт — таблица по всем кейсам и слоям, плюс явное перечисление кейсов, где слои разошлись

Расхождение слоёв — не баг харнесса, а ровно то, ради чего слоёв три: единственная метрика
всегда слепа к какому-то классу ошибок.
"""
import json
import math
import re
import time
from pathlib import Path

import ollama

CANDIDATE_MODEL = "qwen2.5:7b"
JUDGE_MODEL = "llama3.1:8b"
EMBED_MODEL = "nomic-embed-text"

JUDGE_PROMPT = """Ты — технический рецензент. Сравни ответ ассистента с эталонным ответом
на тот же вопрос и оцени фактическую точность и полноту ответа ассистента по шкале от 1 до 5,
где 5 — ответ полностью соответствует эталону по смыслу, 1 — противоречит эталону или не по теме.
Не снижай оценку за другую формулировку, если смысл совпадает.

Первая строка ответа должна быть РОВНО в формате "SCORE: <1-5>", без пояснений в этой строке.
Затем с новой строки одно предложение обоснования.

Вопрос: {question}

Эталонный ответ:
{reference}

Ответ ассистента для оценки:
{answer}
"""


def load_dataset(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases


def generate_answer(question: str) -> str:
    response = ollama.chat(model=CANDIDATE_MODEL, messages=[{"role": "user", "content": question}])
    return response["message"]["content"]


def deterministic_check(answer: str, must_include: list[str], max_words: int) -> dict:
    lowered = answer.lower()
    missing = [kw for kw in must_include if kw.lower() not in lowered]
    word_count = len(answer.split())
    return {
        "keywords_missing": missing,
        "word_count": word_count,
        "within_limit": word_count <= max_words,
        "passed": not missing and word_count <= max_words,
    }


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def embedding_similarity(answer: str, reference: str) -> float:
    # "clustering: " — префикс nomic-embed-text для симметричного сравнения "текст к тексту".
    # search_query/search_document тут не подходят: ни один из двух текстов не запрос к другому.
    embeddings = ollama.embed(
        model=EMBED_MODEL,
        input=[f"clustering: {answer}", f"clustering: {reference}"],
    )["embeddings"]
    return cosine_similarity(embeddings[0], embeddings[1])


def judge_score(question: str, answer: str, reference: str) -> dict:
    prompt = JUDGE_PROMPT.format(question=question, reference=reference, answer=answer)
    response = ollama.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},
    )
    raw = response["message"]["content"]
    match = re.search(r"^SCORE:\s*([1-5])\s*$", raw, re.IGNORECASE | re.MULTILINE)
    if not match:
        return {"score": None, "raw": raw}
    return {"score": int(match.group(1)), "raw": raw}


def main() -> None:
    dataset = load_dataset(Path(__file__).parent / "dataset.jsonl")
    results = []

    for case in dataset:
        print(f"=== {case['id']} ===")
        print(f"Вопрос: {case['question']}")

        t0 = time.time()
        answer = generate_answer(case["question"])
        gen_time = time.time() - t0
        print(f"Ответ кандидата ({CANDIDATE_MODEL}, {gen_time:.1f} с): {answer}")

        det = deterministic_check(answer, case["must_include"], case["max_words"])
        sim = embedding_similarity(answer, case["reference_answer"])
        judge = judge_score(case["question"], answer, case["reference_answer"])

        print(f"  Слой 1 (автотест):    {'ПРОЙДЕН' if det['passed'] else 'НЕ ПРОЙДЕН'} "
              f"(слов: {det['word_count']}, не найдены: {det['keywords_missing'] or '-'})")
        print(f"  Слой 2 (эмбеддинг):   cosine similarity = {sim:.4f}")
        print(f"  Слой 3 (судья {JUDGE_MODEL}): score = {judge['score']}")
        print()

        results.append({"id": case["id"], "det_passed": det["passed"], "similarity": sim, "judge_score": judge["score"]})

    print("=== Итоговый отчёт ===")
    header = f"{'кейс':<16} {'автотест':<10} {'similarity':<12} {'судья 1-5':<10}"
    print(header)
    print("-" * len(header))
    disagreements = []
    for r in results:
        print(f"{r['id']:<16} {'да' if r['det_passed'] else 'нет':<10} {r['similarity']:<12.4f} {str(r['judge_score']):<10}")
        # расхождение слоёв: автотест не прошёл, а два содержательных слоя оценивают ответ высоко —
        # значит формальный критерий (например, набор ключевых слов) был слишком узким
        if not r["det_passed"] and r["similarity"] > 0.7 and (r["judge_score"] or 0) >= 4:
            disagreements.append(r["id"])

    avg_similarity = sum(r["similarity"] for r in results) / len(results)
    avg_judge = sum(r["judge_score"] for r in results if r["judge_score"] is not None) / len(results)
    print(f"\nСредний similarity: {avg_similarity:.4f}, средний балл судьи: {avg_judge:.2f}")

    if disagreements:
        print(f"Расхождение слоёв на кейсах {disagreements}: автотест забраковал ответ, "
              f"который эмбеддинг и судья считают качественным — узкий формальный критерий, а не плохой ответ.")
    else:
        print("Слои согласны на всех кейсах в этом прогоне.")


if __name__ == "__main__":
    main()
