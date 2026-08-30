# torch 2.13.0, transformers 5.15.1, peft 0.20.0, Qwen2.5-0.5B-Instruct,
# прогнано на macOS 26.5.2 (Apple Silicon, MPS) 2026-08-30
"""Ранговая абляция LoRA: как параметр r влияет на число обучаемых параметров
и на размер адаптера на диске.

Для трёх значений ранга (4, 8, 32) на одних и тех же target_modules собирается
свежий адаптер поверх базовой модели. Обучения тут нет — размер и число
параметров у LoRA-матриц зависят только от их формы (r и размерность слоя),
а не от того, обучены веса или только что инициализированы. Это позволяет
увидеть компромисс параметров сразу, без прогона обучения под каждый ранг.
"""

import os
import shutil
import subprocess

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]
RANKS = [4, 8, 32]
OUT_DIR = "rank_adapters"


def adapter_dir_size(path):
    result = subprocess.run(["du", "-sh", path], capture_output=True, text=True)
    return result.stdout.split()[0]


def main():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"устройство: {device}, torch {torch.__version__}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)

    rows = []
    for r in RANKS:
        # Модель грузится заново на каждый ранг: одна и та же модель не может
        # нести два непересекающихся набора LoRA-матриц без явного переключения
        # адаптеров, а свежая загрузка на модели такого размера дёшева.
        model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float32).to(device)

        # alpha держим равной 2*r, чтобы масштаб (alpha/r) был одинаковым для
        # всех рангов и абляция сравнивала только форму матриц, а не масштаб.
        config = LoraConfig(
            r=r,
            lora_alpha=2 * r,
            target_modules=TARGET_MODULES,
            task_type="CAUSAL_LM",
        )
        peft_model = get_peft_model(model, config)

        trainable = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
        total = sum(p.numel() for p in peft_model.parameters())

        adapter_path = os.path.join(OUT_DIR, f"r{r}")
        peft_model.save_pretrained(adapter_path)
        size_on_disk = adapter_dir_size(adapter_path)

        rows.append((r, trainable, 100 * trainable / total, size_on_disk))
        print(f"r={r:>2}: обучаемых параметров {trainable:>9,} "
              f"({100 * trainable / total:.4f}% от {total:,}), адаптер на диске {size_on_disk}")

        del model, peft_model

    print("\nсводка (ранг -> обучаемые параметры -> доля -> размер на диске):")
    for r, trainable, share, size_on_disk in rows:
        print(f"  r={r:>2}: {trainable:>9,} параметров, {share:.4f}%, {size_on_disk}")

    base_to_top = rows[-1][1] / rows[0][1]
    print(f"\nразница параметров между r={RANKS[0]} и r={RANKS[-1]}: {base_to_top:.1f}x")


if __name__ == "__main__":
    main()
