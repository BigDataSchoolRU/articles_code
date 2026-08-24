# torch 2.13.0, transformers 5.15.1, peft 0.20.0, Qwen2.5-0.5B-Instruct,
# прогнано на macOS 26.5.2 (Apple Silicon, MPS) 2026-08-24
"""Сравнение ответов базовой модели и той же модели с LoRA-адаптером.

Одна и та же модель в памяти, один и тот же промпт, одинаковые параметры
генерации (do_sample=False, то есть жадный поиск без случайности). Разница в
ответах целиком объясняется адаптером, а не температурой.

Проверяются два набора вопросов: термины из обучающей выборки и отложенные,
которых модель на обучении не видела. Второй набор показывает, перенёсся ли
формат ответа или модель просто запомнила сорок строк.
"""

import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from dataset import CHAT_TEMPLATE, HELD_OUT, TERMS, build_prompt_messages

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
ADAPTER_DIR = "lora_adapter"
SEEN = [TERMS[0][0], TERMS[8][0]]  # HDFS и Parquet, оба были в обучении
MAX_NEW_TOKENS = 80


def generate(model, tokenizer, term, device):
    """Один жадный прогон генерации на вопрос про термин."""
    text = tokenizer.apply_chat_template(
        build_prompt_messages(term), tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(text, return_tensors="pt").to(device)
    started = time.time()
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    answer = tokenizer.decode(
        output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
    ).strip()
    return answer, time.time() - started


def report(model, tokenizer, device, title):
    print(f"\n===== {title} =====")
    for group, terms in (("из обучения", SEEN), ("отложенные", HELD_OUT)):
        for term in terms:
            answer, seconds = generate(model, tokenizer, term, device)
            one_line = " ".join(answer.split())
            print(f"[{group}] {term} ({seconds:.1f} с)")
            print(f"  {one_line}")


def main():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    # тот же шаблон, что и на обучении: иначе сравнение будет нечестным
    tokenizer.chat_template = CHAT_TEMPLATE
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float32)
    model.to(device)
    model.eval()

    report(model, tokenizer, device, "ДО дообучения (базовая модель)")

    # Тот же объект модели, сверху навешивается обученный адаптер
    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    model.eval()

    report(model, tokenizer, device, "ПОСЛЕ дообучения (базовая модель + LoRA)")


if __name__ == "__main__":
    main()
