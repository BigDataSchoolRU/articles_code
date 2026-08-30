# LLM Evaluation

Код к статье [LLM Evaluation](https://bigdataschool.ru/wiki/llm_evaluation/) на Wiki BigDataSchool.

## Файлы

- `dataset.jsonl` — конфигурация оценки: 4 вопроса, эталонные ответы, критерии автотеста.
- `eval_harness.py` — полный цикл харнесса: генерация ответа кандидатом, оценка тремя
  независимыми слоями (детерминированный автотест, эмбеддинг-сходство, модель-судья), отчёт.
- `judge_stability_cost.py` — нестабильность слоя "модель-судья" при повторных вызовах и
  относительная стоимость трёх слоёв по времени.
- `RUNBOOK.md` — как поднять окружение и прогнать демо у себя.

## Окружение

- Python 3.12+, пакет `ollama`
- [Ollama](https://ollama.com/) с моделями `qwen2.5:7b`, `llama3.1:8b`, `nomic-embed-text`

Подробности и ожидаемый вывод каждого шага — в [RUNBOOK.md](RUNBOOK.md).

## Запуск

```bash
pip install ollama
ollama pull qwen2.5:7b && ollama pull llama3.1:8b && ollama pull nomic-embed-text
python3 eval_harness.py
python3 judge_stability_cost.py
```
