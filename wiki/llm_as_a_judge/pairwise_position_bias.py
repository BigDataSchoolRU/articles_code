# ollama 0.6.2, модели qwen2.5:7b и qwen2.5:0.5b-instruct-q4_0 (кандидаты),
# llama3.1:8b (судья), прогнано на стенде 2026-08-27
"""
LLM-as-a-Judge: pairwise comparison и демонстрация position bias.

Два кандидата разного размера (сильная модель 7B и слабая квантованная 0.5B) отвечают
на один вопрос. Судья сравнивает пару ответов и называет победителя. Затем сравнение
прогоняется ПОВТОРНО с переставленным порядком ответов в промпте (A и B меняются
местами) — если победитель меняется вместе с порядком, а не с содержанием, это и есть
задокументированный position bias LLM-судей.
"""
import re

import ollama

STRONG_MODEL = "qwen2.5:7b"
WEAK_MODEL = "qwen2.5:0.5b-instruct-q4_0"
JUDGE_MODEL = "llama3.1:8b"

QUESTION = "Что такое индекс в базе данных и зачем он нужен?"

PAIRWISE_PROMPT = """Ты — судья, сравнивающий два ответа на один вопрос пользователя.
Определи, какой ответ лучше по точности, полноте и ясности.

Первая строка ответа должна содержать РОВНО ОДНО из трёх слов после "WINNER: " —
либо A, либо B, либо tie (без кавычек, без вертикальных черт, без перечисления
вариантов). Пример правильной первой строки: "WINNER: A".
Затем с новой строки одно предложение обоснования.

Вопрос: {question}

Ответ A:
{answer_a}

Ответ B:
{answer_b}
"""


def get_answer(model: str, question: str) -> str:
    response = ollama.chat(model=model, messages=[{"role": "user", "content": question}])
    return response["message"]["content"]


def judge_pair(question: str, answer_a: str, answer_b: str) -> str:
    prompt = PAIRWISE_PROMPT.format(question=question, answer_a=answer_a, answer_b=answer_b)
    response = ollama.chat(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},
    )
    return response["message"]["content"]


def extract_winner(verdict_text: str) -> str:
    # ищем строку вида "WINNER: A" целиком — если судья дословно повторил шаблон
    # с вариантами через "|", это не валидный вердикт, а сбой формата
    match = re.search(r"^WINNER:\s*(A|B|tie)\s*$", verdict_text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).upper() if match else "не распознано (сбой формата у судьи)"


def main() -> None:
    print(f"Вопрос: {QUESTION}\n")

    strong_answer = get_answer(STRONG_MODEL, QUESTION)
    weak_answer = get_answer(WEAK_MODEL, QUESTION)
    print(f"--- Ответ сильной модели ({STRONG_MODEL}) ---\n{strong_answer}\n")
    print(f"--- Ответ слабой модели ({WEAK_MODEL}) ---\n{weak_answer}\n")

    # прогон 1: сильная модель на позиции A, слабая на позиции B
    verdict_1 = judge_pair(QUESTION, strong_answer, weak_answer)
    winner_1 = extract_winner(verdict_1)
    print("--- Сравнение 1: A=сильная, B=слабая ---")
    print(verdict_1)
    print(f"Победитель по позиции: {winner_1}")
    print()

    # прогон 2: те же ответы, позиции переставлены
    verdict_2 = judge_pair(QUESTION, weak_answer, strong_answer)
    winner_2 = extract_winner(verdict_2)
    print("--- Сравнение 2: A=слабая, B=сильная (позиции переставлены) ---")
    print(verdict_2)
    print(f"Победитель по позиции: {winner_2}")
    print()

    # приводим оба вердикта к "какая модель победила" независимо от позиции в промпте
    model_winner_1 = {"A": "сильная", "B": "слабая", "TIE": "tie"}.get(winner_1, winner_1)
    model_winner_2 = {"A": "слабая", "B": "сильная", "TIE": "tie"}.get(winner_2, winner_2)
    print(f"Итог: прогон 1 -> {model_winner_1} модель, прогон 2 -> {model_winner_2} модель")
    if model_winner_1 != model_winner_2:
        print("POSITION BIAS ОБНАРУЖЕН: вердикт сменился вместе с позицией, а не с содержанием.")
    else:
        print("Position bias не проявился: вердикт устойчив к перестановке позиций.")


if __name__ == "__main__":
    main()
