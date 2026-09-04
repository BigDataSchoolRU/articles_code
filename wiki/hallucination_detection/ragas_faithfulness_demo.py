# ragas 0.4.3, langchain-ollama 1.1.0, локальный судья qwen2.5:7b через Ollama 0.32.13
# (http://localhost:11434), прогнано на стенде 2026-09-03.
#
# pip install ragas langchain-ollama
#
# Важно про баг ragas 0.4.3. Импорт `ragas` в этой версии безусловно тянет
# `from langchain_community.chat_models.vertexai import ChatVertexAI` в ragas/llms/base.py —
# и падает ImportError у всех, кто не работает с Google Vertex AI, включая пользователей
# Ollama/OpenAI/Anthropic. Баг подтверждён в трекере ragas (issues #2741, #2745, #2753 в
# репозитории vibrantlabsai/ragas), официальный фикс на дату прогона не выпущен. Обходной путь
# ниже — подставить в sys.modules пустую заглушку модуля до импорта ragas, как предлагают
# сами мейнтейнеры в обсуждении бага.
import sys
import types

_vertexai_stub = types.ModuleType("langchain_community.chat_models.vertexai")
_vertexai_stub.ChatVertexAI = None
sys.modules["langchain_community.chat_models.vertexai"] = _vertexai_stub

import asyncio

from langchain_ollama import ChatOllama
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import LangchainLLMWrapper

# ragas.metrics.Faithfulness помечен в 0.4.3 как deprecated в пользу
# ragas.metrics.collections.Faithfulness, но у новой версии в документации нет примера
# с локальным судьёй через LangChain-обёртку (только через ragas.llms.llm_factory и клиент
# OpenAI). Берём документированную для Ollama связку LangchainLLMWrapper + ChatOllama, она
# работает с этим же классом Faithfulness.
from ragas.metrics import Faithfulness

# Судья — локальная модель через Ollama, обёрнутая для интерфейса ragas.
judge = ChatOllama(model="qwen2.5:7b", temperature=0)
evaluator_llm = LangchainLLMWrapper(judge)
scorer = Faithfulness(llm=evaluator_llm)

# Контекст один и тот же для всех трёх случаев — это то, что реально вернул бы retrieval
# в RAG-пайплайне. Faithfulness не проверяет сам факт против внешнего мира, только
# согласованность ответа с этим контекстом.
context = [
    "Первая игра чемпионата AFL-NFL (позже названная Суперкубком I) была сыграна 15 января "
    "1967 года на стадионе Los Angeles Memorial Coliseum в Лос-Анджелесе."
]

cases = {
    "полностью согласован с контекстом": SingleTurnSample(
        user_input="Когда был первый Суперкубок?",
        response="Первый Суперкубок состоялся 15 января 1967 года.",
        retrieved_contexts=context,
    ),
    "частично согласован (место верно, зрители выдуманы)": SingleTurnSample(
        user_input="Когда был первый Суперкубок и где он прошёл?",
        response=(
            "Первый Суперкубок прошёл 15 января 1967 года на стадионе Los Angeles Memorial "
            "Coliseum, его посетили более 100 000 зрителей."
        ),
        retrieved_contexts=context,
    ),
    "полностью выдуман (дата верна, город и посещаемость нет)": SingleTurnSample(
        user_input="Когда был первый Суперкубок и где он прошёл?",
        response=(
            "Первый Суперкубок прошёл 15 января 1967 года в Далласе, его посетили более "
            "100 000 зрителей."
        ),
        retrieved_contexts=context,
    ),
}


async def main() -> None:
    print("Faithfulness Score = доля утверждений ответа, подтверждённых контекстом.\n")
    for label, sample in cases.items():
        score = await scorer.single_turn_ascore(sample)
        print(f"{score:.3f} | {label}")
        print(f"  ответ: {sample.response}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
