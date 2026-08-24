# torch 2.13.0, transformers 5.15.1, peft 0.20.0, trl 1.10.0, Qwen2.5-0.5B-Instruct,
# прогнано на macOS 26.5.2 (Apple Silicon, MPS) 2026-08-24
"""LoRA-дообучение маленькой языковой модели на локальной машине.

Что происходит по шагам:
1. Грузим базовую модель в float32 на MPS (на Apple Silicon это ускоритель вместо CUDA).
2. Вешаем LoRA-адаптеры на матрицы внимания: базовые веса заморожены, учатся
   только низкоранговые A и B.
3. Гоняем SFT по чат-разметке так, чтобы функция потерь считалась только по
   токенам ответа ассистента, а не по системному промпту и вопросу.
4. Сохраняем адаптер отдельным каталогом и печатаем его размер.
"""

import json
import os
import subprocess
import time

import torch
from datasets import Dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

from dataset import CHAT_TEMPLATE, train_records

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
ADAPTER_DIR = "lora_adapter"
SEED = 42


def main():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"устройство: {device}, torch {torch.__version__}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    # Шаблон с разметкой ответа: без него assistant_only_loss работать не может
    tokenizer.chat_template = CHAT_TEMPLATE
    # float32: на MPS половинная точность в обучении даёт нестабильный loss
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float32)
    model.config.use_cache = False  # несовместимо с расчётом градиентов

    records = train_records()
    dataset = Dataset.from_list(records)
    print(f"примеров в обучающей выборке: {len(dataset)}")

    # Ранг r задаёт размер низкоранговых матриц, alpha масштабирует их вклад.
    # target_modules: проекции внутри блока внимания, классический минимум для LoRA.
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        task_type="CAUSAL_LM",
    )

    training_args = SFTConfig(
        output_dir="checkpoints",
        num_train_epochs=8,
        per_device_train_batch_size=4,
        learning_rate=2e-4,
        lr_scheduler_type="constant",
        logging_steps=5,
        max_length=256,
        packing=False,
        # loss только по токенам ответа: вопрос модель воспроизводить не учим
        assistant_only_loss=True,
        save_strategy="no",
        report_to=[],
        seed=SEED,
        disable_tqdm=True,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        processing_class=tokenizer,
        peft_config=lora_config,
    )

    # Доля обучаемых параметров: главная цифра, ради которой LoRA и берут
    trainable = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in trainer.model.parameters())
    print(f"всего параметров: {total:,}")
    print(f"обучаемых параметров: {trainable:,} ({100 * trainable / total:.3f}%)")

    started = time.time()
    result = trainer.train()
    elapsed = time.time() - started

    history = [row for row in trainer.state.log_history if "loss" in row]
    if history:
        print(f"loss на старте: {history[0]['loss']:.4f}")
        print(f"loss в конце:   {history[-1]['loss']:.4f}")
    print(f"шагов обучения: {result.global_step}")
    print(f"время обучения: {elapsed:.1f} с")

    trainer.save_model(ADAPTER_DIR)
    size = subprocess.run(["du", "-sh", ADAPTER_DIR], capture_output=True, text=True)
    print(f"адаптер сохранён: {size.stdout.strip()}")
    for name in sorted(os.listdir(ADAPTER_DIR)):
        print(f"  {name}")

    with open("train_metrics.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "trainable_params": trainable,
                "total_params": total,
                "trainable_share_percent": round(100 * trainable / total, 4),
                "steps": result.global_step,
                "seconds": round(elapsed, 1),
                "loss_first": history[0]["loss"] if history else None,
                "loss_last": history[-1]["loss"] if history else None,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()
