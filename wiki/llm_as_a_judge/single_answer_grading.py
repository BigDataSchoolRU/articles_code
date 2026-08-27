# ollama 0.6.2, модели qwen2.5:7b (кандидат) и llama3.1:8b (судья), прогнано на стенде 2026-08-27
"""
LLM-as-a-Judge: single-answer grading (reference-free).

Кандидатная модель отвечает на технический вопрос. Модель-судья не знает "эталонного"
ответа — она оценивает кандидатный ответ по явной рубрике (критерии + шкала) и возвращает
структурированный вердикт: оценку по каждому критерию, итоговый балл и обоснование словами.
Это и есть механизм LLM-as-a-Judge: рубрика + контент -> вердикт на естественном языке ->
парсинг в структуру.
"""
import json
import re

import ollama

CANDIDATE_MODEL = "qwen2.5:7b"
JUDGE_MODEL = "llama3.1:8b"

QUESTION = (
    "Объясни, что такое переобучение (overfitting) в машинном обучении "
    "и как с ним бороться. Дай 2-3 практических способа."
)

RUBRIC = """Ты — строгий технический рецензент. Оцени ответ ассистента на вопрос пользователя
по четырём критериям, каждый по шкале от 1 до 5:
- accuracy: фактическая точность (нет ошибок и вымышленных утверждений)
- completeness: полнота (вопрос раскрыт, даны практические способы, если просили)
- clarity: ясность изложения
- safety: нет вредных или вводящих в заблуждение рекомендаций

Верни СТРОГО JSON без пояснений вне JSON, в формате:
{{"accuracy": <1-5>, "completeness": <1-5>, "clarity": <1-5>, "safety": <1-5>,
 "total": <сумма>, "verdict": "<1-2 предложения обоснования>"}}

Вопрос пользователя:
{question}

Ответ ассистента для оценки:
{answer}
"""


def get_candidate_answer(question: str) -> str:
    response = ollama.chat(
        model=CANDIDATE_MODEL,
        messages=[{"role": "user", "content": question}],
    )
    return response["message"]["content"]


def judge_answer(question: str, answer: str) -> dict:
    prompt = RUBRIC.format(question=question, answer=answer)
    response = ollama.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},
    )
    raw = response["message"]["content"]
    # судья иногда оборачивает JSON в текст или markdown-блок — вытаскиваем первую {...}
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"parse_error": True, "raw": raw}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"parse_error": True, "raw": raw}


def main() -> None:
    print(f"Вопрос: {QUESTION}\n")

    answer = get_candidate_answer(QUESTION)
    print(f"--- Ответ кандидата ({CANDIDATE_MODEL}) ---")
    print(answer)
    print()

    verdict = judge_answer(QUESTION, answer)
    print(f"--- Вердикт судьи ({JUDGE_MODEL}) ---")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
