# langgraph 1.2.11, прогнано на стенде 2026-08-27
"""Фиксирует дословный текст предупреждения об устаревании
`create_react_agent`, которое реально бросает установленная версия
LangGraph 1.2.11 при вызове функции (не при импорте)."""

import warnings

from langgraph.prebuilt import create_react_agent


def run() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        def dummy_tool(x: str) -> str:
            """Фиктивный инструмент, нужен только чтобы вызов не упал раньше предупреждения."""
            return x

        create_react_agent(model="ollama:qwen2.5:7b", tools=[dummy_tool])

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        if not deprecation_warnings:
            print("предупреждение об устаревании не поймано")
            return
        w = deprecation_warnings[0]
        print(f"категория: {w.category.__name__}")
        print(f"текст: {w.message}")
        print(f"файл: {w.filename}:{w.lineno}")


if __name__ == "__main__":
    run()
