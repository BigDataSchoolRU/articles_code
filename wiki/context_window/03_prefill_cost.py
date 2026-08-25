# ollama 0.32.13, python-клиент ollama 0.6.2, модель qwen2.5:7b, прогнано на стенде 2026-08-24
# Сколько стоит длинный контекст. Меряем префилл, то есть обработку промпта до первого
# токена ответа, на растущей длине входа. Длина ответа зафиксирована, меняется только вход.

import time
import ollama

MODEL = "qwen2.5:7b"
NUM_CTX = 8192  # окно фиксировано, чтобы рантайм не резал промпт по-разному

FILLER_UNIT = (
    "Регламент обслуживания предписывает проверять узел раз в квартал. "
    "Результат проверки заносится в журнал и подписывается ответственным. "
)
TASK = "\n\nОдним словом: о чём этот текст?"

client = ollama.Client()

# Прогрев: первый вызов после смены num_ctx перезагружает модель и меряет не то
client.chat(model=MODEL, messages=[{"role": "user", "content": "привет"}],
            options={"num_ctx": NUM_CTX, "num_predict": 4, "temperature": 0})

print("| единиц наполнителя | токенов промпта | префилл, с | токенов/с на префилле | полный ответ, с |")
print("|---|---|---|---|---|")

rows = []
for units in (10, 40, 80, 120):
    prompt = FILLER_UNIT * units + TASK
    t = time.time()
    resp = client.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"num_ctx": NUM_CTX, "num_predict": 8, "temperature": 0},
    )
    total = time.time() - t
    # ollama отдаёт длительности в наносекундах
    prefill_s = resp.get("prompt_eval_duration", 0) / 1e9
    tokens = resp.get("prompt_eval_count", 0)
    speed = tokens / prefill_s if prefill_s else 0
    rows.append((tokens, prefill_s))
    print(f"| {units} | {tokens} | {prefill_s:.2f} | {speed:.0f} | {total:.2f} |")

# Во сколько раз выросли вход и время его обработки
(t0, p0), (t1, p1) = rows[0], rows[-1]
print(f"\nВход вырос в {t1 / t0:.1f} раза, время префилла в {p1 / p0:.1f} раза.")
print("Префилл обрабатывает промпт целиком на каждый вызов: длинное окно платится на каждом ходу.")
