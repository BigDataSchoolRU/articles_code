# Python 3.12 stdlib, ollama 0.40.13, модель qwen2.5:7b, прогнано на стенде 2026-11-05
"""Компакция истории агента: полная история, очистка выводов инструментов и резюме.

Агент шесть шагов собирает отчёт по ошибкам платёжного сервиса. Требования к отчёту
пользователь дал в самом первом сообщении, а в выводе первого SQL-запроса лежит число,
которое потом спросят. Выводы инструментов многословные, как у настоящих логов и SQL.

Варианты истории перед финальным вопросом:
  full    - вся история как есть;
  clear   - выводы инструментов старше двух последних заменены короткой заглушкой
            (tool result clearing), сами вызовы и реплики остаются;
  summary - история заменена резюме, которое написала та же модель, плюс два последних шага.

Два вопроса к каждому варианту: про раннее требование (формат отчёта) и про деталь из
вывода первого инструмента (сколько строк вернул запрос). Печатается ответ, верен ли он,
токены промпта, сколько из них Ollama взяла из кэша префикса и сколько секунд ушло на
чтение остальных, для summary отдельно цена самого сжатия. Кэш здесь не сбивается
намеренно: очистка и резюме переписывают начало истории, и кэш префикса после них
перестаёт работать, это часть цены компакции.
"""
import json
import os
import sys
import time
import urllib.request

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
NUM_CTX = 8192
KEEP_LAST = 2   # сколько последних шагов с инструментами оставлять нетронутыми

SYSTEM = ("Ты агент-аналитик. Работаешь с базой платежей инструментами run_sql и read_logs. "
          "Отвечай кратко и только по фактам из истории.")
TASK = ("Собери отчёт по ошибкам сервиса payments за неделю 2026-10-26 - 2026-11-01. "
        "Требования к отчёту: формат CSV, разделитель точка с запятой, кодировка UTF-8, "
        "файл положить в каталог /reports/payments. Ошибки таймаута в отчёт не включать.")

QUESTIONS = [
    ("требование", "Перед сохранением: в каком формате, с каким разделителем и в какой каталог "
                   "сохранить отчёт? Ответь одной строкой.",
     lambda a: "csv" in a.lower() and ("точк" in a.lower() or ";" in a) and "/reports/payments" in a),
    ("деталь", "Сколько строк вернул самый первый SQL-запрос? Ответь одним числом.",
     lambda a: "1287" in a.replace(" ", "")),
]


def log_lines(n, start, code):
    # многословный вывод, как у настоящего read_logs: время, уровень, trace id, текст
    return "\n".join(f"2026-10-{start + i % 5:02d}T0{i % 10}:1{i % 6}:2{i % 9}Z ERROR payments "
                     f"trace={code}{i:04d}ab7f code={code} msg=\"upstream {code} for merchant m{100 + i}\""
                     for i in range(n))


def sql_rows(n):
    return "\n".join(f"| {d} | {c} | {cnt} |" for d, c, cnt in
                     [(f"2026-10-{26 + i % 6}", ["DECLINED", "TIMEOUT", "FRAUD", "5XX"][i % 4], 40 + i * 13)
                      for i in range(n)])


# шесть шагов агента: вызов инструмента и его многословный результат
STEPS = [
    ("run_sql", {"query": "SELECT * FROM payment_errors WHERE ts BETWEEN '2026-10-26' AND '2026-11-01'"},
     "Запрос выполнен за 2.4 с. Возвращено строк: 1287.\n| day | code | count |\n" + sql_rows(12)),
    ("run_sql", {"query": "SELECT code, count(*) FROM payment_errors GROUP BY code"},
     "| code | count |\n| DECLINED | 611 |\n| TIMEOUT | 402 |\n| FRAUD | 158 |\n| 5XX | 116 |\nВсего 4 строки."),
    ("read_logs", {"service": "payments", "level": "ERROR", "limit": 14},
     log_lines(14, 26, "5XX")),
    ("read_logs", {"service": "payments-gateway", "level": "ERROR", "limit": 14},
     log_lines(14, 27, "DECLINED")),
    ("run_sql", {"query": "SELECT merchant_id, count(*) FROM payment_errors WHERE code='FRAUD' GROUP BY 1 ORDER BY 2 DESC LIMIT 10"},
     "| merchant_id | count |\n" + "\n".join(f"| m{200 + i} | {30 - i * 2} |" for i in range(10))),
    ("run_sql", {"query": "SELECT count(*) FROM payment_errors WHERE code <> 'TIMEOUT'"},
     "| count |\n| 885 |"),
]


def history():
    msgs = [{"role": "user", "content": TASK}]
    for name, args, result in STEPS:
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": name, "arguments": args}}]})
        msgs.append({"role": "tool", "content": result})
    msgs.append({"role": "assistant", "content": "Данные собраны: 885 ошибок без таймаутов, "
                                                 "разбивка по кодам и топ мерчантов по FRAUD готовы."})
    return msgs


def chat(messages, num_predict):
    body = {"model": MODEL, "messages": messages, "stream": False, "keep_alive": "60m",
            "options": {"temperature": 0, "seed": 42, "num_ctx": NUM_CTX, "num_predict": num_predict}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as resp:
        return json.load(resp)


def cleared(msgs):
    # tool result clearing: старые выводы инструментов заменяются заглушкой, вызовы остаются
    tool_idx = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
    out = [dict(m) for m in msgs]
    for i in tool_idx[:-KEEP_LAST]:
        out[i]["content"] = "[вывод инструмента очищен, вызов можно повторить]"
    return out


def summarized(msgs):
    # компакция: модель сама пишет резюме ранней истории, два последних шага остаются как есть
    cut = [i for i, m in enumerate(msgs) if m["role"] == "assistant" and m.get("tool_calls")][-KEEP_LAST]
    early, tail = msgs[:cut], msgs[cut:]
    prompt = [{"role": "system", "content": SYSTEM}] + early + [{"role": "user", "content":
              "Сожми историю выше для продолжения работы. Сохрани требования пользователя, "
              "принятые решения и ключевые числа. Не больше 80 слов."}]
    t = time.time()
    r = chat(prompt, num_predict=160)
    summary = r["message"]["content"].strip()
    print(f"сжатие: прочитано {r['prompt_eval_count']} токенов (из кэша "
          f"{r.get('prompt_eval_cached_count', 0)}), написано {r['eval_count']}, "
          f"{time.time() - t:.1f} с")
    print("резюме:", summary.replace("\n", " "))
    return [{"role": "user", "content": f"Резюме предыдущей работы:\n{summary}"}] + tail


def main():
    full = history()
    print(f"модель {MODEL}, num_ctx {NUM_CTX}, шагов с инструментами {len(STEPS)}, KEEP_LAST {KEEP_LAST}")
    variants = [("full", full), ("clear", cleared(full)), ("summary", summarized(full))]
    for name, msgs in variants:
        for qname, q, check in QUESTIONS:
            t = time.time()
            r = chat([{"role": "system", "content": SYSTEM}] + msgs + [{"role": "user", "content": q}], 40)
            a = r["message"]["content"].strip().replace("\n", " ")
            print(f"{name:<8} {qname:<11} токенов промпта {r['prompt_eval_count']:>5}  "
                  f"из кэша {r.get('prompt_eval_cached_count', 0):>5}  "
                  f"префилл {r['prompt_eval_duration'] / 1e9:6.1f} с  всего {time.time() - t:6.1f} с  "
                  f"верно {'да ' if check(a) else 'нет'}  ответ: {a[:80]}")


if __name__ == "__main__":
    main()
