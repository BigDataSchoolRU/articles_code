# hallucination_detection

Код к статье https://bigdataschool.ru/wiki/hallucination_detection/

Два независимых демо детекции галлюцинаций: классификатор Vectara HHEM-2.1-Open (локально, без
внешних вызовов) и метрика RAGAS Faithfulness с LLM-судьёй через Ollama.

## Состав

| Файл | Что делает |
|---|---|
| `hhem_scoring_demo.py` | скоринг четырёх пар (источник, сгенерированный текст) моделью HHEM-2.1-Open — одна дословно точная, две с явной галлюцинацией, одна точная, но перефразированная |
| `ragas_faithfulness_demo.py` | RAGAS Faithfulness с локальным судьёй `qwen2.5:7b` через Ollama на трёх ответах (полностью согласован, частично, полностью выдуман) с одним и тем же контекстом |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором типовых ошибок, включая известный баг ragas 0.4.3 |

## Окружение

Python 3.12. Демо HHEM и демо RAGAS требуют разных версий `transformers` (см. `RUNBOOK.md`,
почему), поэтому заведены два venv. Демо RAGAS дополнительно требует запущенной локально Ollama
с моделью `qwen2.5:7b`.

## Как запустить

```bash
python3.12 -m venv .venv_hhem && .venv_hhem/bin/pip install "transformers==4.46.3" "torch==2.13.0"
.venv_hhem/bin/python3 hhem_scoring_demo.py

python3.12 -m venv .venv && .venv/bin/pip install ragas langchain-ollama
ollama serve &
ollama pull qwen2.5:7b
.venv/bin/python3 ragas_faithfulness_demo.py
```

Подробности по каждому шагу, ожидаемый вывод и разбор граблей — в `RUNBOOK.md`.
