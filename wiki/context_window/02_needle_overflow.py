# ollama 0.32.13, python-клиент ollama 0.6.2, модель qwen2.5:7b, прогнано на стенде 2026-08-24
# Что происходит с фактом, который не поместился в контекстное окно.
# Кладём «иголку» в самое начало длинного промпта и гоняем один и тот же запрос
# при разных значениях num_ctx. Рантайм режет то, что не влезло, и модель отвечает
# уверенно и неправильно, а не сообщает об ошибке.

import time
import ollama

MODEL = "qwen2.5:7b"
NEEDLE = "Кодовое слово проекта: ГРАНАТ-77."
QUESTION = "Какое кодовое слово проекта названо в тексте выше? Ответь только словом и числом."

# Наполнитель: осмысленный, но бесполезный для ответа текст
FILLER_UNIT = (
    "Отдел эксплуатации ведёт журнал регламентных работ. "
    "Записи содержат дату, ответственного и краткое описание операции. "
    "Журнал хранится в общей папке и еженедельно выгружается в архив. "
)


def build_prompt(units: int) -> str:
    """Иголка в начале, за ней много наполнителя, в конце вопрос."""
    return NEEDLE + "\n\n" + FILLER_UNIT * units + "\n\n" + QUESTION


client = ollama.Client()
prompt = build_prompt(55)
print(f"Длина промпта: {len(prompt)} символов")

# Замер длины промпта в токенах: гоняем его с заведомо большим окном
probe = client.chat(model=MODEL, messages=[{"role": "user", "content": prompt}],
                    options={"num_ctx": 16384, "num_predict": 4, "temperature": 0})
full_tokens = probe.get("prompt_eval_count")
print(f"Промпт целиком: {full_tokens} токенов")

print("\n| num_ctx | токенов промпта учтено | время, с | ответ модели | иголка найдена |")
print("|---|---|---|---|---|")

for num_ctx in (1024, 2048, 4096, 8192):
    t = time.time()
    resp = client.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"num_ctx": num_ctx, "num_predict": 32, "temperature": 0},
    )
    elapsed = time.time() - t
    answer = resp["message"]["content"].strip().replace("\n", " ")[:60]
    # prompt_eval_count это то, сколько токенов промпта рантайм реально посчитал
    counted = resp.get("prompt_eval_count")
    found = "да" if "ГРАНАТ" in answer.upper() and "77" in answer else "нет"
    print(f"| {num_ctx} | {counted} | {elapsed:.1f} | {answer} | {found} |")

print("\nПояснение: при маленьком num_ctx рантайм отбрасывает начало промпта,")
print("вместе с ним пропадает иголка, и модель отвечает по остатку текста.")
print("Смотрите на колонку учтённых токенов: пока промпт влезает в окно, он идёт целиком.")
print("Как только не влезает, Ollama оставляет примерно половину окна, и обрезается начало.")
