# ollama (python client) 0.6.2, сервер ollama 0.32.13, прогнано на стенде 2026-08-30
"""
Жизненный цикл запроса к Ollama через REST API (обёрнутый python-клиентом):
обычный вызов chat, потоковая генерация токен за токеном, вызов инструмента (tool calling).
Модель qwen2.5:7b уже загружена на стенде.
"""
import time

import ollama

MODEL = "qwen2.5:7b"


def demo_chat():
    # Один запрос-ответ: клиент шлёт POST /api/chat, сервер грузит модель в память
    # (если ещё не загружена) и возвращает готовый ответ целиком.
    t0 = time.time()
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "Сколько будет 17 умножить на 6? Ответь только числом."}],
    )
    elapsed = time.time() - t0
    print(f"[chat] {elapsed:.2f} с -> {response['message']['content'].strip()}")


def demo_stream():
    # stream=True переключает тот же эндпоинт на потоковую передачу: сервер отдаёт
    # NDJSON построчно, каждая строка — один сгенерированный фрагмент токенов.
    print("[stream] ", end="", flush=True)
    t0 = time.time()
    chunk_count = 0
    for chunk in ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "Объясни в одном предложении, что такое REST API."}],
        stream=True,
    ):
        print(chunk["message"]["content"], end="", flush=True)
        chunk_count += 1
    elapsed = time.time() - t0
    print(f"\n[stream] {chunk_count} фрагментов за {elapsed:.2f} с")


def get_weather(city: str) -> str:
    # Заглушка вместо реального похода в погодный API — интересен сам механизм
    # вызова инструмента, а не источник данных.
    fake_data = {"Москва": "-3°C, снег", "Дубай": "+34°C, ясно"}
    return fake_data.get(city, "нет данных")


def demo_tool_calling():
    # Модель не вызывает функцию сама — она возвращает structured tool_calls,
    # а выполнение и подстановку результата обратно в диалог делает клиентский код.
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Текущая погода в городе",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "Название города"}},
                    "required": ["city"],
                },
            },
        }
    ]
    messages = [{"role": "user", "content": "Какая погода в Дубае?"}]
    response = ollama.chat(model=MODEL, messages=messages, tools=tools)
    tool_calls = response["message"].get("tool_calls") or []
    if not tool_calls:
        print("[tools] модель не запросила вызов инструмента:", response["message"]["content"])
        return

    call = tool_calls[0]
    args = call["function"]["arguments"]
    result = get_weather(args["city"])
    print(f"[tools] модель запросила get_weather({args}) -> {result}")

    # Результат инструмента возвращается модели отдельным сообщением с role="tool",
    # только после этого второго вызова получается связный ответ на языке пользователя.
    messages.append(response["message"])
    messages.append({"role": "tool", "content": result})
    final = ollama.chat(model=MODEL, messages=messages)
    print(f"[tools] финальный ответ -> {final['message']['content'].strip()}")


if __name__ == "__main__":
    demo_chat()
    demo_stream()
    demo_tool_calling()
