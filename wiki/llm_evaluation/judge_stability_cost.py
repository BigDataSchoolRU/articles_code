# ollama 0.6.2, модель llama3.1:8b (судья), прогнано на стенде 2026-08-30
"""
Два ограничения модели-судьи, которые не видны на одном прогоне: нестабильность и стоимость.

Нестабильность: один и тот же вопрос/ответ/эталон отправляется судье N раз подряд без
изменений во входе. temperature=0 должна давать одинаковый балл на каждом повторе — это и
проверяем. Затем то же самое с temperature=0.7, где разброс ожидаем по конструкции модели.

Стоимость: одна и та же пара "ответ + эталон" оценивается тремя слоями харнесса
(eval_harness.py), и меряется время каждого слоя. Детерминированный автотест не ходит в
модель вообще, эмбеддинг — один короткий вызов, судья — самый тяжёлый: длинный промпт с
рубрикой плюс генерация обоснования, а не одного числа.
"""
import re
import statistics
import time

import ollama

JUDGE_MODEL = "llama3.1:8b"
REPEATS = 5

QUESTION = "Зачем нужен индекс в базе данных?"
REFERENCE = (
    "Индекс — это дополнительная структура данных, которая ускоряет поиск и выборку строк "
    "по значению столбца, избавляя от полного сканирования таблицы, но замедляет операции "
    "записи и занимает место на диске."
)
# фиксированный ответ кандидата, не эталонный дословно, но верный по сути — типичный кейс
# для судьи, а не для точного строкового сравнения
ANSWER = (
    "Индекс ускоряет поиск нужных строк в таблице, потому что базе не нужно просматривать "
    "все записи подряд. Платить за это приходится местом на диске и более медленной записью, "
    "так как индекс тоже нужно обновлять."
)

JUDGE_PROMPT = """Ты — технический рецензент. Сравни ответ ассистента с эталонным ответом
на тот же вопрос и оцени фактическую точность и полноту ответа ассистента по шкале от 1 до 5,
где 5 — ответ полностью соответствует эталону по смыслу, 1 — противоречит эталону или не по теме.

Первая строка ответа должна быть РОВНО в формате "SCORE: <1-5>", без пояснений в этой строке.
Затем с новой строки одно предложение обоснования.

Вопрос: {question}

Эталонный ответ:
{reference}

Ответ ассистента для оценки:
{answer}
"""


def judge_once(temperature: float) -> tuple[int | None, float]:
    t0 = time.time()
    response = ollama.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(question=QUESTION, reference=REFERENCE, answer=ANSWER)}],
        options={"temperature": temperature},
    )
    elapsed = time.time() - t0
    raw = response["message"]["content"]
    match = re.search(r"^SCORE:\s*([1-5])\s*$", raw, re.IGNORECASE | re.MULTILINE)
    return (int(match.group(1)) if match else None, elapsed)


def measure_stability(temperature: float) -> None:
    scores = []
    times = []
    for i in range(REPEATS):
        score, elapsed = judge_once(temperature)
        scores.append(score)
        times.append(elapsed)
        print(f"  прогон {i + 1}: score={score}, {elapsed:.1f} с")
    valid = [s for s in scores if s is not None]
    spread = max(valid) - min(valid) if valid else None
    print(f"  баллы: {scores}, разброс (max-min): {spread}, среднее время: {statistics.mean(times):.1f} с")


def measure_layer_cost() -> None:
    # слой 1: детерминированный автотест — без сети и без модели
    t0 = time.time()
    missing = [kw for kw in ["ускоря", "запис"] if kw not in ANSWER.lower()]
    det_time = time.time() - t0
    print(f"  слой 1 (автотест):  {det_time * 1000:.2f} мс, не найдено ключевых слов: {missing or '-'}")

    # слой 2: эмбеддинг-сходство — один короткий вызов модели
    t0 = time.time()
    ollama.embed(model="nomic-embed-text", input=[f"clustering: {ANSWER}", f"clustering: {REFERENCE}"])
    embed_time = time.time() - t0
    print(f"  слой 2 (эмбеддинг): {embed_time:.2f} с")

    # слой 3: судья — длинный промпт с рубрикой, генерация обоснования, а не одного числа
    _, judge_time = judge_once(temperature=0)
    print(f"  слой 3 (судья):     {judge_time:.2f} с")
    print(f"  судья дороже эмбеддинга в {judge_time / embed_time:.1f} раза")


def main() -> None:
    print("=== Нестабильность: temperature=0, 5 повторов одного и того же входа ===")
    measure_stability(temperature=0)

    print("\n=== Нестабильность: temperature=0.7, 5 повторов ===")
    measure_stability(temperature=0.7)

    print("\n=== Стоимость трёх слоёв на одном кейсе ===")
    measure_layer_cost()


if __name__ == "__main__":
    main()
