# python-клиент ollama 0.6.2, Ollama 0.32.13, модели qwen2.5:0.5b-instruct-{q4_0,q8_0,fp16}
# прогнано на стенде 2026-08-26 (macOS 26.5.2, arm64)
#
# Сравнивает три варианта квантования одной и той же модели: размер файла на диске,
# скорость генерации (холодный вызов с загрузкой весов и тёплый вызов сразу после)
# и сам текст ответа на одном и том же промпте.

import time
import ollama

TAGS = [
    "qwen2.5:0.5b-instruct-q4_0",
    "qwen2.5:0.5b-instruct-q8_0",
    "qwen2.5:0.5b-instruct-fp16",
]

PROMPT = "Объясни в двух предложениях, что такое квантование модели."


def model_size_mb(name: str) -> float:
    for m in ollama.list()["models"]:
        if m["model"] == name:
            return m["size"] / (1024 * 1024)
    raise RuntimeError(f"модель {name} не найдена в `ollama list`, сначала ollama pull")


def timed_call(name: str) -> dict:
    t0 = time.time()
    resp = ollama.chat(
        model=name,
        messages=[{"role": "user", "content": PROMPT}],
        options={"num_predict": 200},
    )
    wall = time.time() - t0
    eval_count = resp.get("eval_count", 0)
    eval_duration_s = resp.get("eval_duration", 0) / 1e9
    tok_s = eval_count / eval_duration_s if eval_duration_s > 0 else 0.0
    return {
        "wall_s": wall,
        "eval_count": eval_count,
        "tok_s": tok_s,
        "text": resp["message"]["content"].strip(),
    }


def main() -> None:
    print(f"промпт: {PROMPT!r}\n")
    rows = []
    for tag in TAGS:
        size_mb = model_size_mb(tag)
        cold = timed_call(tag)  # первый вызов после переключения модели, с загрузкой весов
        warm = timed_call(tag)  # второй вызов сразу следом, веса уже в памяти
        rows.append((tag, size_mb, cold, warm))

        print(f"=== {tag} ===")
        print(f"размер на диске: {size_mb:.1f} МБ")
        print(f"холодный вызов: {cold['wall_s']:.2f} с, {cold['tok_s']:.1f} ток/с "
              f"({cold['eval_count']} токенов)")
        print(f"тёплый вызов:   {warm['wall_s']:.2f} с, {warm['tok_s']:.1f} ток/с "
              f"({warm['eval_count']} токенов)")
        print(f"ответ (тёплый вызов): {warm['text']}")
        print()

    print("=== СВОДНАЯ ТАБЛИЦА ===")
    print(f"{'тег':32} {'МБ':>8} {'холодный ток/с':>16} {'тёплый ток/с':>14}")
    for tag, size_mb, cold, warm in rows:
        print(f"{tag:32} {size_mb:8.1f} {cold['tok_s']:16.1f} {warm['tok_s']:14.1f}")


if __name__ == "__main__":
    main()
