# ollama (python client) 0.6.2, сервер ollama 0.32.13, модель qwen2.5:7b, прогнано на стенде 2026-08-27
"""
Демонстрация того же механизма, который лежит в основе prompt caching у вендоров
(Anthropic, OpenAI): переиспользование уже посчитанного KV-состояния для повторяющегося
префикса запроса, без пересчёта токенов заново.

Локальный Ollama не биллингует кэш и не даёт явных cache_control-точек, как Anthropic, но
у него та же механика на уровне движка: если новый запрос продолжает ровно тот же префикс,
что был в предыдущем запросе к этой же модели, движок не пересчитывает префикс заново.
Единственный надёжный сигнал переиспользования в ответе Ollama — prompt_eval_duration (сколько
времени ушло на обработку промпта). Поле prompt_eval_count сигналом не служит: оно всегда равно
полной длине промпта, даже когда бо́льшая его часть не пересчитывалась заново. Скрипт не
воспроизводит биллинг вендоров, он показывает тот же факт архитектуры: повторный проход по
неизменному префиксу дешевле нового.

Пять вызовов подряд к одной и той же модели:
  1. turn1_cold_prefix            — длинный статичный системный промпт + первый вопрос, с нуля.
  2. turn2_continue_same_prefix   — тот же диалог продолжается вторым вопросом.
  3. turn3_continue_same_prefix   — тот же диалог продолжается третьим вопросом.
  4. turn4_prefix_changed_one_char — НОВЫЙ диалог, тот же системный промпт с изменением
     на один символ, отправлен сразу после turn3 (последним состоянием движка был turn3).
  5. turn5_original_prefix_out_of_sequence — тот же самый запрос, что и turn1 (оригинальный,
     неизменный префикс), но отправлен не сразу после себя, а после turn4.

Ожидание по документации: 2 и 3 быстрее 1 по prompt-стороне, потому что префикс уже обработан.
Что покажет turn4 и turn5 — не подгоняется заранее, это и есть предмет измерения (пилот).
"""

import json
import time

import ollama

MODEL = "qwen2.5:7b"
NUM_CTX = 8192
NUM_PREDICT = 30  # мало токенов на выходе, чтобы не смазывать замер на стороне промпта

# Реалистичный системный промпт агента поддержки: персона, правила, две карточки тарифов.
# Специально длинный и неизменяемый между ходами — ровно то, что в статье описано как
# сценарий с наибольшей выгодой от prompt caching (агентный/диалоговый сценарий).
LONG_SYSTEM_PROMPT = """Ты — агент поддержки продукта CloudMetrics (SaaS-платформа мониторинга
инфраструктуры). Отвечай кратко, по-русски, только на основании данных ниже. Если ответа нет
в данных — прямо скажи, что не знаешь, и предложи передать вопрос человеку. Не придумывай цены,
лимиты и даты, которых нет в карточках тарифов ниже. Не упоминай, что ты языковая модель. Дата
снимка данных: 2026-08-27.

Правила общения:
- Обращение на "вы", без канцелярита и лишних извинений.
- Один ответ — один прямой вывод, без пересказа вопроса клиента.
- Если вопрос касается сразу двух тарифов — сравнение таблицей из двух-трёх строк.
- Скидки, промокоды и индивидуальные условия — только если они прямо указаны в карточке тарифа.
- При вопросе про технические лимиты (retention, число агентов, частота опроса) — цитировать
  цифру из карточки дословно, единицы измерения не менять и не округлять.

Карточка тарифа Pro:
- Цена: 4 900 руб/мес за проект, без ограничения на число пользователей аккаунта.
- Retention метрик: 30 дней при разрешении 10 секунд, далее агрегация до 5 минут на 400 дней.
- Число агентов мониторинга: до 200 хостов на проект.
- Алерты: до 50 правил, каналы — email, Slack, Telegram, Webhook.
- SLA поддержки: ответ в течение 8 рабочих часов, канал — почта и чат в личном кабинете.
- Годовая оплата: скидка 15% от суммы 12 месяцев при оплате разом.
- Не входит: SSO, кастомные дашборды на API, выделенный TAM.

Карточка тарифа Enterprise:
- Цена: по индивидуальному расчёту, зависит от числа хостов и retention; агенту менеджера для
  расчёта не давать, всегда направлять на форму заявки на сайте.
- Retention метрик: настраиваемый, минимум 400 дней на полном разрешении.
- Число агентов мониторинга: без верхнего предела тарифа, лимит только по контракту.
- Алерты: без ограничения по числу правил, дополнительно PagerDuty и Opsgenie.
- SLA поддержки: ответ в течение 1 часа, круглосуточно, выделенный TAM.
- Годовая оплата: обязательна, помесячной оплаты на этом тарифе нет.
- Входит: SSO (SAML, OIDC), кастомные дашборды через API, аудит-лог действий команды.

Типовые вопросы, на которые уже есть точный ответ выше: цена Pro, что входит в Enterprise,
разница retention между тарифами, наличие SSO, условия годовой оплаты, число хостов на Pro.
Всё, чего нет в карточках (например точная цена Enterprise, наличие скидки для НКО, миграция
данных между тарифами) — эскалация на человека, а не предположение.
"""


def chat_turn(messages: list[dict], label: str) -> tuple[dict, dict]:
    t0 = time.time()
    resp = ollama.chat(
        model=MODEL,
        messages=messages,
        stream=False,
        options={"num_ctx": NUM_CTX, "temperature": 0, "num_predict": NUM_PREDICT},
    )
    wall_s = time.time() - t0
    stats = {
        "label": label,
        "wall_s": round(wall_s, 2),
        "prompt_eval_count": resp.prompt_eval_count,
        "prompt_eval_duration_s": round((resp.prompt_eval_duration or 0) / 1e9, 3),
        "eval_count": resp.eval_count,
        "eval_duration_s": round((resp.eval_duration or 0) / 1e9, 3),
        "total_duration_s": round((resp.total_duration or 0) / 1e9, 3),
        "load_duration_s": round((resp.load_duration or 0) / 1e9, 3),
    }
    print(f"\n--- {label} ---")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return resp, stats


def main() -> None:
    print(f"=== Прогрев модели {MODEL} (короткий вызов без длинного префикса) ===")
    ollama.chat(model=MODEL, messages=[{"role": "user", "content": "ping"}], options={"num_ctx": NUM_CTX})

    q1 = "Клиент спрашивает: сколько стоит тариф Pro?"
    messages = [
        {"role": "system", "content": LONG_SYSTEM_PROMPT},
        {"role": "user", "content": q1},
    ]
    resp1, s1 = chat_turn(messages, "turn1_cold_prefix")
    messages.append({"role": "assistant", "content": resp1.message.content})

    messages.append({"role": "user", "content": "А что входит в тариф Enterprise?"})
    resp2, s2 = chat_turn(messages, "turn2_continue_same_prefix")
    messages.append({"role": "assistant", "content": resp2.message.content})

    messages.append({"role": "user", "content": "Есть ли SSO на тарифе Pro?"})
    resp3, s3 = chat_turn(messages, "turn3_continue_same_prefix")

    broken_prefix = LONG_SYSTEM_PROMPT.replace("2026-08-27", "2026-08-28", 1)
    messages_broken = [
        {"role": "system", "content": broken_prefix},
        {"role": "user", "content": q1},
    ]
    resp4, s4 = chat_turn(messages_broken, "turn4_prefix_changed_one_char")

    messages_original_again = [
        {"role": "system", "content": LONG_SYSTEM_PROMPT},
        {"role": "user", "content": q1},
    ]
    resp5, s5 = chat_turn(messages_original_again, "turn5_original_prefix_out_of_sequence")

    print("\n=== Итог: все замеры ===")
    print(json.dumps([s1, s2, s3, s4, s5], ensure_ascii=False, indent=2))

    print("\n=== Вывод по числам ===")
    print(f"turn1 (холодный префикс): prompt_eval_count={s1['prompt_eval_count']}, "
          f"prompt_eval_duration_s={s1['prompt_eval_duration_s']}")
    print(f"turn2 (продолжение):      prompt_eval_count={s2['prompt_eval_count']}, "
          f"prompt_eval_duration_s={s2['prompt_eval_duration_s']}")
    print(f"turn3 (продолжение):      prompt_eval_count={s3['prompt_eval_count']}, "
          f"prompt_eval_duration_s={s3['prompt_eval_duration_s']}")
    print(f"turn4 (сдвиг + 1 символ): prompt_eval_count={s4['prompt_eval_count']}, "
          f"prompt_eval_duration_s={s4['prompt_eval_duration_s']}")
    print(f"turn5 (тот же turn1, но не подряд): prompt_eval_count={s5['prompt_eval_count']}, "
          f"prompt_eval_duration_s={s5['prompt_eval_duration_s']}")


if __name__ == "__main__":
    main()
