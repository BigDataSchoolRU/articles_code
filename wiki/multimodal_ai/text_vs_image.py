# ollama 0.6.2, модель qwen2.5vl:7b, Ollama 0.32.13, прогнано на стенде 2026-08-24
"""Сравнивает две модальности с одинаковым содержимым на одной модели.

Сначала таблица уходит картинкой, потом ровно та же таблица уходит текстом.
Вопрос и модель одни и те же, отличается только модальность входа. Разница в
prompt_eval_count показывает, во сколько обходится визуальная форма данных.
"""
import time

import ollama

from make_sample import AS_TEXT, build

MODEL = "qwen2.5vl:7b"
QUESTION = "В каком квартале выручка максимальная и чему она равна?"


def run(label, message):
    """Один запрос к модели с замером токенов промпта и времени."""
    started = time.time()
    reply = ollama.chat(
        model=MODEL,
        messages=[message],
        options={"num_ctx": 8192, "temperature": 0},
    )
    print(
        f"{label}: токенов промпта {reply['prompt_eval_count']}, "
        f"время {round(time.time() - started, 1)} с"
    )
    print(f"  ответ: {reply['message']['content'].strip()}")


def main():
    path = build("sales_table.png", 1200, 800)
    print(f"модель {MODEL}, вопрос: {QUESTION}")
    # модальность 1: та же таблица картинкой
    run("картинка", {"role": "user", "content": QUESTION, "images": [path]})
    # модальность 2: та же таблица обычным текстом
    run("текст", {"role": "user", "content": f"{QUESTION}\n\n{AS_TEXT}"})


if __name__ == "__main__":
    main()
