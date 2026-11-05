# Python 3.12 stdlib, ollama 0.40.13, модель qwen2.5:7b, прогнано на стенде 2026-11-05
"""Из чего состоит окно агента: вклад каждого слоя контекста в токенах.

Окно одного шага агента собирается из пяти слоёв: системный промпт, описания инструментов,
история сообщений с выводами инструментов, извлечённые документы и текущий вопрос.
Скрипт добавляет слои по одному и после каждого спрашивает у Ollama, сколько токенов
промпта модель прочитала (prompt_eval_count, вызов с num_predict=1, ответ не нужен).
Разница между соседними замерами и есть вклад слоя.

prompt_eval_count в Ollama 0.40.13 считает всё окно, включая токены, взятые из кэша
префикса (они отдельно лежат в prompt_eval_cached_count). Слои добавляются в конец окна,
поэтому каждый следующий замер дочитывает только новый слой, а цифра окна остаётся полной.
"""
import json
import os
import sys
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
NUM_CTX = 8192

SYSTEM = ("Ты агент поддержки интернет-магазина. Помогаешь оператору разбирать обращения "
          "клиентов: находишь заказ, проверяешь статус доставки и оплаты, предлагаешь решение. "
          "Возврат денег оформляешь только после проверки статуса оплаты. Отвечай кратко.")


def tool(name, desc, props):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "required": list(props),
        "properties": {k: {"type": "string", "description": v} for k, v in props.items()}}}}


# двенадцать инструментов: в реальных агентах их набор растёт быстрее всего остального
TOOLS = [
    tool("find_order", "Найти заказ по номеру или телефону клиента", {"query": "номер заказа или телефон"}),
    tool("order_status", "Статус заказа и история его изменений", {"order_id": "номер заказа"}),
    tool("payment_status", "Статус оплаты заказа в платёжном шлюзе", {"order_id": "номер заказа"}),
    tool("delivery_track", "Трек и статус доставки у перевозчика", {"order_id": "номер заказа"}),
    tool("refund", "Оформить возврат денег по заказу", {"order_id": "номер заказа", "reason": "причина"}),
    tool("cancel_order", "Отменить заказ до передачи в доставку", {"order_id": "номер заказа", "reason": "причина"}),
    tool("change_address", "Изменить адрес доставки", {"order_id": "номер заказа", "address": "новый адрес"}),
    tool("customer_profile", "Профиль клиента: контакты, заказы, обращения", {"customer_id": "id клиента"}),
    tool("search_kb", "Поиск по базе знаний поддержки", {"query": "текст запроса"}),
    tool("create_ticket", "Создать задачу во внутренний трекер", {"title": "заголовок", "body": "описание"}),
    tool("send_sms", "Отправить клиенту SMS", {"phone": "телефон", "text": "текст"}),
    tool("escalate", "Передать обращение старшему оператору", {"order_id": "номер заказа", "note": "комментарий"}),
]

HISTORY = [
    {"role": "user", "content": "Клиент пишет, что заказ 58213 не пришёл, а деньги списали неделю назад."},
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "order_status", "arguments": {"order_id": "58213"}}}]},
    {"role": "tool", "content": json.dumps({"order_id": "58213", "status": "shipped", "history": [
        {"ts": f"2026-10-{d:02d}T1{d % 10}:00:00Z", "status": s, "by": "system", "comment": c}
        for d, s, c in [(27, "created", "заказ создан на сайте"), (27, "paid", "оплата картой подтверждена"),
                        (28, "assembled", "собран на складе Север-2"), (28, "shipped", "передан перевозчику"),
                        (29, "in_transit", "принят на сортировке"), (30, "in_transit", "задержка на сортировке")]]},
        ensure_ascii=False)},
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "delivery_track", "arguments": {"order_id": "58213"}}}]},
    {"role": "tool", "content": json.dumps({"carrier": "СДЭК", "track": "1129384756", "events": [
        {"ts": f"2026-10-{d:02d}T0{d % 10}:30:00Z", "place": p, "event": e}
        for d, p, e in [(28, "Москва, склад", "принято от отправителя"), (29, "Москва, СЦ", "сортировка"),
                        (30, "Москва, СЦ", "задержка: повреждение упаковки"), (31, "Москва, СЦ", "ожидает переупаковки")]]},
        ensure_ascii=False)},
    {"role": "assistant", "content": "Посылка застряла на сортировке из-за повреждённой упаковки. Проверяю оплату."},
]

DOCS = ("Извлечённые документы базы знаний:\n"
        "[kb-114] Повреждение упаковки у перевозчика: если посылка ждёт переупаковки дольше 3 дней, "
        "оператор создаёт задачу в трекер с треком и предлагает клиенту выбор: ждать или вернуть деньги.\n"
        "[kb-087] Возврат денег по оплаченному заказу оформляется после проверки статуса оплаты, срок "
        "зачисления на карту до 10 рабочих дней.\n"
        "[kb-203] Компенсация за задержку доставки: промокод 10% при задержке больше 5 дней по вине перевозчика.")

QUESTION = {"role": "user", "content": "Что ответить клиенту и что сделать по заказу?"}


def prompt_tokens(messages, tools=None):
    # num_predict=1: ответ не нужен, нужен только счётчик прочитанных токенов
    body = {"model": MODEL, "messages": messages, "stream": False, "keep_alive": "60m",
            "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 1}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as resp:
        r = json.load(resp)
    return r["prompt_eval_count"], r.get("prompt_eval_cached_count", 0)


def main():
    system = {"role": "system", "content": SYSTEM}
    docs = {"role": "user", "content": DOCS}
    # слои добавляются по одному, как окно растёт от пустого агента к реальному шагу
    steps = [
        ("системный промпт", [system], None),
        ("+ инструменты (12)", [system], TOOLS),
        ("+ история с выводами", [system] + HISTORY, TOOLS),
        ("+ документы (3)", [system] + HISTORY + [docs], TOOLS),
        ("+ вопрос", [system] + HISTORY + [docs, QUESTION], TOOLS),
    ]
    print(f"модель {MODEL}, num_ctx {NUM_CTX}")
    print(f"{'слой':<24}{'окно, ток':>10}{'вклад':>8}{'доля':>7}{'из кэша':>9}")
    rows, prev = [], 0
    for name, msgs, tools in steps:
        n, cached = prompt_tokens(msgs, tools)
        rows.append((name, n, n - prev, cached))
        prev = n
    total = rows[-1][1]
    for name, n, delta, cached in rows:
        print(f"{name:<24}{n:>10}{delta:>8}{delta / total:>7.0%}{cached:>9}")
    print(f"итого окно {total} токенов из {NUM_CTX}: {total / NUM_CTX:.0%} num_ctx, "
          f"вопрос пользователя {rows[-1][2]} токенов")


if __name__ == "__main__":
    main()
