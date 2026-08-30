# torch 2.13.0, transformers 5.15.1, peft 0.20.0, Qwen2.5-0.5B-Instruct,
# прогнано на macOS 26.5.2 (Apple Silicon, MPS) 2026-08-30
"""Задержка инференса до и после merge_and_unload().

Пока адаптер не слит, каждый forward-проход считает выход базового слоя и
отдельно выход низкоранговой ветки B·A, а потом складывает их — это лишние
операции на каждом из целевых слоёв. merge_and_unload() один раз складывает
B·A с исходной матрицей (W' = W + B·A) и возвращает обычную модель без
LoRA-обвязки: дальше это просто более быстрый forward той же архитектуры.

Обучение здесь короткое и без completion-only маскирования — цель не качество
ответа, а получить адаптер с реально изменившимися (не нулевыми) весами, чтобы
слияние было не косметическим.
"""

import time

import torch
from peft import LoraConfig, get_peft_model
from torch.optim import AdamW
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
EPOCHS = 5
GENERATE_REPEATS = 10

TRAIN_PAIRS = [
    ("Что такое LoRA?", "LoRA обучает две низкоранговые матрицы поверх замороженных весов вместо всей модели."),
    ("Что такое PEFT?", "PEFT — семейство методов дообучения, где обновляется малая доля параметров модели."),
    ("Что такое квантование?", "Квантование переводит веса модели в формат меньшей разрядности ради экономии памяти."),
    ("Что такое эмбеддинг?", "Эмбеддинг — числовой вектор фиксированной длины, кодирующий смысл текста."),
    ("Что такое батч?", "Батч — порция примеров, обрабатываемая за один шаг обучения перед обновлением весов."),
    ("Что такое переобучение?", "Переобучение — состояние модели, когда она запомнила выборку и хуже работает на новых данных."),
    ("Что такое градиентный спуск?", "Градиентный спуск сдвигает веса модели против направления градиента функции потерь."),
    ("Что такое токенизация?", "Токенизация разбивает текст на единицы словаря, которые модель получает вместо символов."),
]


def measure_generate(model, inputs, repeats):
    # Первый вызов на MPS всегда дороже: компиляция ядер и перенос весов
    # в исполняемое состояние. Его результат в замер не идёт.
    with torch.no_grad():
        model.generate(**inputs, max_new_tokens=30, do_sample=False)
    times = []
    for _ in range(repeats):
        started = time.time()
        with torch.no_grad():
            model.generate(**inputs, max_new_tokens=30, do_sample=False)
        times.append(time.time() - started)
    return times


def main():
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"устройство: {device}, torch {torch.__version__}")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float32).to(device)
    model.config.use_cache = False  # несовместимо с расчётом градиентов при обучении

    config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        task_type="CAUSAL_LM",
    )
    peft_model = get_peft_model(model, config)
    peft_model.print_trainable_parameters()

    examples = []
    for question, answer in TRAIN_PAIRS:
        text = f"Вопрос: {question}\nОтвет: {answer}{tokenizer.eos_token}"
        ids = tokenizer(text, return_tensors="pt").input_ids.to(device)
        examples.append(ids)

    optimizer = AdamW([p for p in peft_model.parameters() if p.requires_grad], lr=2e-4)

    peft_model.train()
    started = time.time()
    for epoch in range(EPOCHS):
        epoch_loss = 0.0
        for ids in examples:
            output = peft_model(input_ids=ids, labels=ids)
            output.loss.backward()
            optimizer.step()
            optimizer.zero_grad()
            epoch_loss += output.loss.item()
        print(f"эпоха {epoch + 1}: loss {epoch_loss / len(examples):.4f}")
    print(f"обучение {EPOCHS} эпох на {len(examples)} примерах: {time.time() - started:.1f} с")

    peft_model.eval()
    model.config.use_cache = True  # обратно на инференс: KV-кэш ускоряет генерацию

    prompt = "Вопрос: Что такое дообучение?\nОтвет:"
    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    adapter_times = measure_generate(peft_model, inputs, GENERATE_REPEATS)
    adapter_avg = sum(adapter_times) / len(adapter_times)
    print(f"генерация с адаптером (не слитым): {adapter_avg:.3f} с в среднем по {GENERATE_REPEATS} прогонам")

    merged_model = peft_model.merge_and_unload()
    merged_times = measure_generate(merged_model, inputs, GENERATE_REPEATS)
    merged_avg = sum(merged_times) / len(merged_times)
    print(f"генерация после merge_and_unload: {merged_avg:.3f} с в среднем по {GENERATE_REPEATS} прогонам")

    print(f"ускорение после слияния: {adapter_avg / merged_avg:.2f}x")


if __name__ == "__main__":
    main()
