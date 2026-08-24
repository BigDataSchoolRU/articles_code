# ollama 0.6.2, модель qwen2.5vl:7b, Ollama 0.32.13, прогнано на стенде 2026-08-24
"""Показывает, что изображение внутри мультимодальной модели это токены.

Одну и ту же таблицу подаём в трёх разрешениях и смотрим на prompt_eval_count,
то есть на длину промпта, которую модель реально обработала. Текст запроса при
этом не меняется, поэтому весь прирост даёт картинка.
"""
import time

import ollama

from make_sample import build

MODEL = "qwen2.5vl:7b"
QUESTION = "Какая выручка в Q4? Ответь одним числом."
CORRECT = "18.7"  # верный ответ известен заранее, таблицу рисовали мы сами
SIZES = [(150, 100), (600, 400), (2400, 1600)]


def ask(path):
    """Шлёт картинку и вопрос в модель, возвращает ответ, токены промпта и время."""
    started = time.time()
    reply = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": QUESTION, "images": [path]}],
        options={"num_ctx": 8192, "temperature": 0},
    )
    return (
        reply["message"]["content"].strip(),
        reply["prompt_eval_count"],
        round(time.time() - started, 1),
    )


def main():
    print(f"модель {MODEL}, вопрос: {QUESTION}")
    baseline = None
    for width, height in SIZES:
        path = build(f"sales_{width}x{height}.png", width, height)
        answer, tokens, seconds = ask(path)
        if baseline is None:
            baseline = tokens
        print(
            f"{width}x{height}: токенов промпта {tokens}, "
            f"рост к минимальному {tokens / baseline:.1f}x, "
            f"время {seconds} с, ответ: {answer}, верно: {CORRECT in answer}"
        )


if __name__ == "__main__":
    main()
