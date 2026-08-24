# Дообучение модели (Fine-tuning)

Код к статье [Дообучение модели (Fine-tuning)](https://bigdataschool.ru/wiki/fine_tuning/).

LoRA-дообучение модели Qwen2.5-0.5B-Instruct на выборке из сорока пар «вопрос — ответ».
Всё считается локально на MPS (Apple Silicon), видеокарта NVIDIA не нужна.

## Состав

| Файл | Что внутри |
|---|---|
| `dataset.py` | обучающая выборка на 40 пар, отложенные термины и шаблон чата с разметкой ответа |
| `train_lora.py` | обучение LoRA-адаптера через TRL SFTTrainer, метрики в `train_metrics.json` |
| `compare_before_after.py` | ответы базовой модели и её же с адаптером на одни и те же вопросы |
| `requirements.txt` | версии пакетов, зафиксированные по факту прогона |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором типовых граблей |

## Окружение

macOS 26.5.2 (arm64), Python 3.12.13, torch 2.13.0, transformers 5.15.1, peft 0.20.0,
trl 1.10.0. Около 3 ГБ на диске под веса модели и пакеты.

## Как запустить

```bash
python3.12 -m venv .venv
./.venv/bin/python3 -m pip install -r requirements.txt
./.venv/bin/python3 train_lora.py
./.venv/bin/python3 compare_before_after.py
```

Подробности по шагам, ожидаемый вывод и что делать, если пошло не так, — в
[RUNBOOK.md](RUNBOOK.md).

## Что получилось на прогоне

Обучаемых параметров 1 081 344 из 495 114 112, это 0,218%. Восемь эпох заняли 171 секунду,
loss упал с 2,59 до 0,65. Файл весов адаптера `adapter_model.safetensors` весит 4,35 МБ
против 953 МБ у базовой модели.
