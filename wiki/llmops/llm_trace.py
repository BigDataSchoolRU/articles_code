# LLMOps demo, прогнано на Python 3.12.13, ollama-python 0.6.2, Ollama 0.32.9, модель qwen2.5:7b
"""Минимальный LLMOps-контур: версионированный промпт плюс трассировка каждого вызова."""

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ollama

BASE_DIR = Path(__file__).resolve().parent
TRACE_FILE = BASE_DIR / "traces.jsonl"
# Модель это такой же параметр конфигурации, как адрес базы: её меняют без правки кода.
MODEL = os.getenv("LLMOPS_MODEL", "qwen2.5:7b")

# Реестр промптов. Каждая версия это отдельный артефакт релиза: правка текста
# меняет поведение системы так же, как в MLOps его меняет новый файл модели.
PROMPTS = {
    "support_classifier": {
        "v1": "Определи категорию обращения пользователя.",
        "v2": (
            "Ты классификатор обращений в техподдержку. "
            "Ответь ровно одним словом из списка: billing, access, performance, bug, other. "
            "Никаких пояснений, знаков препинания и заглавных букв."
        ),
    }
}

# Условный тариф провайдера в рублях за 1000 токенов. Локальная модель денег не стоит,
# но поле оставлено намеренно: в проде стоимость запроса это такая же метрика, как латентность.
PRICE_IN_PER_1K = 0.15
PRICE_OUT_PER_1K = 0.60


def resolve_prompt(name: str, version: str) -> tuple[str, str]:
    """Возвращает текст промпта и его короткий хеш, который уезжает в трейс."""
    text = PROMPTS[name][version]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return text, digest


def ask(name: str, version: str, user_text: str, temperature: float = 0.0, seed: int | None = 42) -> dict:
    """Один вызов модели с замером латентности, токенов и стоимости, запись трейса в JSONL."""
    system_prompt, digest = resolve_prompt(name, version)
    # Без seed Ollama сама выбирает случайное зерно, и повторный вызов даёт другой ответ.
    options = {"temperature": temperature}
    if seed is not None:
        options["seed"] = seed
    started = time.perf_counter()
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        options=options,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    tokens_in = response.prompt_eval_count or 0
    tokens_out = response.eval_count or 0
    cost_rub = round(
        tokens_in / 1000 * PRICE_IN_PER_1K + tokens_out / 1000 * PRICE_OUT_PER_1K, 5
    )

    record = {
        "trace_id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "prompt_name": name,
        "prompt_version": version,
        "prompt_hash": digest,
        "temperature": temperature,
        "input": user_text,
        "output": response.message.content.strip(),
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_rub": cost_rub,
    }
    # Трейс дописывается построчно: JSONL переживает падение процесса и читается любым инструментом.
    with TRACE_FILE.open("a", encoding="utf-8") as trace:
        trace.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


if __name__ == "__main__":
    demo = ask("support_classifier", "v2", "Списали деньги дважды за один и тот же тариф")
    print(json.dumps(demo, ensure_ascii=False, indent=2))
