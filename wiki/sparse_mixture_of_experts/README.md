# Sparse Mixture-of-Experts

Код к статье https://bigdataschool.ru/wiki/sparse_mixture_of_experts/

Игрушечный Sparse MoE-слой на чистом PyTorch (8 экспертов, каждый — обычный
двухслойный FFN): top-k роутинг, capacity factor с token dropping и
auxiliary loss, балансирующий нагрузку экспертов.

## Состав

| Файл | Что делает |
|---|---|
| `topk_router.py` | top-1 (Switch Transformer) против top-2 (GShard) роутинг на одном батче токенов, счётчик активных параметров на токен против общих параметров слоя |
| `capacity_and_aux_loss.py` | capacity factor и token dropping при переполнении эксперта, auxiliary loss (формула Switch Transformer) на сбалансированном роутере и на роутере со смещением в один эксперт (имитация коллапса) |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и разбором граблей |

## Окружение

macOS 26.5.2 (arm64), Python 3.12.13, PyTorch 2.13.0. GPU не нужен, всё на CPU.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/pip install torch
./.venv/bin/python3 topk_router.py
./.venv/bin/python3 capacity_and_aux_loss.py
```

Подробности по каждому шагу и что должно быть в выводе — в `RUNBOOK.md`.
