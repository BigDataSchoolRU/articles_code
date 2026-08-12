# LLMOps demo, прогнано на Python 3.12.13, ollama-python 0.6.2, Ollama 0.32.9, модель qwen2.5:7b
"""Offline-eval двух версий промпта плюс проба на недетерминированность."""

import statistics

from llm_trace import ask

# Набор кейсов с эталоном. Это регрессионный тест LLM-приложения: он гоняется
# на каждую правку промпта и на каждую смену версии модели.
CASES = [
    ("Списали деньги дважды за один и тот же тариф", "billing"),
    ("Не приходит письмо для сброса пароля", "access"),
    ("Отчёт строится восемь минут вместо десяти секунд", "performance"),
    ("Кнопка экспорта роняет вкладку браузера", "bug"),
    ("Хочу узнать, когда у вас корпоративы", "other"),
    ("Не могу войти под своей учётной записью", "access"),
    ("Счёт выставлен на юрлицо, а нужен на другое", "billing"),
    ("Приложение виснет при загрузке файла больше 100 мегабайт", "performance"),
]


def normalize(answer: str) -> str:
    """Модель любит добавлять точки, кавычки и заглавные буквы, эталон от этого не меняется."""
    return answer.strip().strip('.,!"\'`«»').lower()


def run_version(version: str) -> dict:
    """Прогоняет весь набор на одной версии промпта и считает агрегаты."""
    passed, latencies, tokens, cost = 0, [], 0, 0.0
    for text, expected in CASES:
        record = ask("support_classifier", version, text)
        ok = normalize(record["output"]) == expected
        passed += ok
        latencies.append(record["latency_ms"])
        tokens += record["tokens_in"] + record["tokens_out"]
        cost += record["cost_rub"]
        mark = "OK  " if ok else "FAIL"
        print(f"  {mark} ожидали={expected:<12} получили={record['output'][:60]!r}")
    return {
        "version": version,
        "pass_rate": round(passed / len(CASES) * 100),
        "latency_median_ms": round(statistics.median(latencies)),
        "latency_max_ms": max(latencies),
        "tokens": tokens,
        "cost_rub": round(cost, 4),
    }


def drift_probe(runs: int = 3) -> None:
    """Один и тот же вход без фиксированного seed даёт разные ответы, и это штатное поведение."""
    question = "Списали деньги дважды за один и тот же тариф"
    answers = [
        ask("support_classifier", "v1", question, temperature=0.8, seed=None)["output"]
        for _ in range(runs)
    ]
    unique = len(set(answers))
    print(f"  уникальных ответов на один вход: {unique} из {runs}")
    for number, answer in enumerate(answers, start=1):
        print(f"  [{number}] {answer[:100]}")


if __name__ == "__main__":
    results = []
    for version in ("v1", "v2"):
        print(f"\n=== Прогон версии промпта {version} ===")
        results.append(run_version(version))

    print("\n=== Сводка ===")
    header = f"{'версия':<8}{'pass rate':<12}{'медиана мс':<14}{'макс мс':<10}{'токены':<9}{'руб':<8}"
    print(header)
    for row in results:
        print(
            f"{row['version']:<8}{str(row['pass_rate']) + '%':<12}"
            f"{row['latency_median_ms']:<14}{row['latency_max_ms']:<10}"
            f"{row['tokens']:<9}{row['cost_rub']:<8}"
        )

    print("\n=== Проба на недетерминированность ===")
    drift_probe()
