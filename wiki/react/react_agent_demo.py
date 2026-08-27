# langchain 1.3.15, langchain-ollama 1.1.0, langgraph 1.2.11, qwen2.5:7b, прогнано на стенде 2026-08-27
"""Цикл ReAct (Thought -> Action -> Observation) на текущем API `create_agent`
из `langchain.agents`. Модель не может ответить на вопрос без инструмента:
сравнение длины двух слов не тривиально для LLM посимвольно, поэтому она
вызывает инструмент `word_length` дважды и только потом формулирует ответ.
"""

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama


@tool
def word_length(word: str) -> int:
    """Возвращает точное число символов в слове."""
    return len(word)


def run() -> None:
    llm = ChatOllama(model="qwen2.5:7b", temperature=0)
    agent = create_agent(
        model=llm,
        tools=[word_length],
        system_prompt=(
            "Ты решаешь задачу пошагово. Перед каждым вызовом инструмента "
            "коротко объясни в тексте, зачем он тебе нужен (это твоя мысль, "
            "Thought). После получения результата инструмента (Observation) "
            "либо вызови инструмент ещё раз, либо дай финальный ответ."
        ),
    )

    question = (
        "Какое из двух слов длиннее: 'наблюдаемость' или 'архитектура'? "
        "Ответь названием более длинного слова и разницей в символах."
    )

    result = agent.invoke({"messages": [{"role": "user", "content": question}]})

    print("=== Полный трейс цикла ReAct ===")
    for i, msg in enumerate(result["messages"]):
        role = msg.__class__.__name__
        tool_calls = getattr(msg, "tool_calls", None)
        if role == "AIMessage" and tool_calls:
            print(f"[{i}] {role} (Thought, если есть, в content) -> Action:")
            if msg.content:
                print(f"    Thought: {msg.content}")
            for call in tool_calls:
                print(f"    Action: {call['name']}({call['args']})")
        elif role == "ToolMessage":
            print(f"[{i}] {role} -> Observation: {msg.content}")
        else:
            print(f"[{i}] {role}: {msg.content}")

    print("\n=== Финальный ответ ===")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    run()
