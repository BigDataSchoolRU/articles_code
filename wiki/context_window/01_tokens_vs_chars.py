# tiktoken 0.13.0, кодировка cl100k_base, прогнано на стенде 2026-08-24
# Считаем, во сколько токенов обходится один и тот же текст на русском и на английском.
# Бюджет контекстного окна меряется в токенах, а не в символах, и курс обмена у языков разный.

import tiktoken

# cl100k_base это токенизатор семейства GPT-4/GPT-3.5, взят как общедоступный ориентир
enc = tiktoken.get_encoding("cl100k_base")

PAIRS = [
    ("русский", "Контекстное окно это максимальное число токенов, которое модель обрабатывает за один вызов."),
    ("english", "The context window is the maximum number of tokens a model processes in a single call."),
    ("код", "def count(text: str) -> int:\n    return len(enc.encode(text))"),
    ("числа", "2026-08-24 12:30:59 latency=4.31s tokens=1024"),
]

print("| текст | символов | токенов | символов на токен |")
print("|---|---|---|---|")
for label, text in PAIRS:
    chars = len(text)
    tokens = len(enc.encode(text))
    print(f"| {label} | {chars} | {tokens} | {chars / tokens:.2f} |")

# Разбор одного слова по токенам: видно, что редкое кириллическое слово рубится на куски
word = "Контекстное"
ids = enc.encode(word)
parts = [enc.decode([i]) for i in ids]
print(f"\nСлово '{word}' -> {len(ids)} токенов: {parts}")

word_en = "Context"
ids_en = enc.encode(word_en)
print(f"Слово '{word_en}' -> {len(ids_en)} токенов: {[enc.decode([i]) for i in ids_en]}")

# Практический вывод для планирования бюджета окна
ru = PAIRS[0][1]
en = PAIRS[1][1]
ratio = (len(ru) / len(enc.encode(ru))) / (len(en) / len(enc.encode(en)))
print(f"\nПлотность русского текста относительно английского: {ratio:.2f}")
print("Один и тот же смысл на русском съедает заметно больше бюджета окна.")
