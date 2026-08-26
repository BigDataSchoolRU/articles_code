# llama-index-core 0.14.24, llama-index-llms-ollama 0.10.1, llama-index-embeddings-ollama 0.9.0
# модели: ollama qwen2.5:7b (LLM) и nomic-embed-text (эмбеддинги), прогнано на стенде 2026-08-26
"""
Базовый RAG-пайплайн на LlamaIndex поверх локальной Ollama:
Loading & Indexing -> Storing -> Querying & Retrieval -> Response Synthesis.
Корпус — внутренняя база знаний компании, вопрос пользователя закрывается
одним конкретным документом, остальные документы намеренно про смежные темы.
"""
import time

from llama_index.core import Document, VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama

# Модель для генерации ответа и модель для эмбеддингов задаются глобально через Settings,
# дальше индекс и query engine используют их без явной передачи в каждый вызов.
Settings.llm = Ollama(model="qwen2.5:7b", request_timeout=120)
Settings.embed_model = OllamaEmbedding(model_name="nomic-embed-text")

KNOWLEDGE_BASE = [
    Document(
        text=(
            "Регламент доступа к продуктивным базам данных: доступ на чтение выдаётся "
            "на 90 дней, на запись — на 30 дней, оформляется заявкой в системе управления "
            "доступом с подтверждением руководителя и владельца системы."
        ),
        metadata={"title": "Доступ к продуктивным БД"},
    ),
    Document(
        text=(
            "Регламент удалённой работы: сотрудник вправе работать удалённо до трёх дней "
            "в неделю по согласованию с руководителем, подключение к внутренним сервисам "
            "только через корпоративный VPN с двухфакторной аутентификацией."
        ),
        metadata={"title": "Удалённая работа и VPN"},
    ),
    Document(
        text=(
            "Порядок оформления отпуска: заявление подаётся в кадровую систему не позднее "
            "чем за две недели до даты начала отпуска, график отпусков утверждается "
            "руководителем подразделения в начале календарного года."
        ),
        metadata={"title": "Оформление отпуска"},
    ),
    Document(
        text=(
            "Возврат корпоративного оборудования: при увольнении сотрудник обязан сдать "
            "ноутбук, пропуск и токены доступа в течение последнего рабочего дня, иначе "
            "стоимость оборудования удерживается из расчёта при увольнении."
        ),
        metadata={"title": "Возврат оборудования"},
    ),
    Document(
        text=(
            "Регламент код-ревью: любой пул-реквест в основную ветку требует минимум одного "
            "одобрения от другого разработчика команды, автоматические проверки (линтер, "
            "тесты) должны пройти до запроса ревью."
        ),
        metadata={"title": "Код-ревью"},
    ),
    Document(
        text=(
            "Порядок компенсации обучения: компания возмещает стоимость курсов повышения "
            "квалификации до 100 000 рублей в год при условии, что сотрудник отработает "
            "в компании не менее года после окончания курса."
        ),
        metadata={"title": "Компенсация обучения"},
    ),
]


def main():
    t0 = time.time()
    index = VectorStoreIndex.from_documents(KNOWLEDGE_BASE)
    print(f"Индексация {len(KNOWLEDGE_BASE)} документов заняла {time.time() - t0:.2f} с")
    print("Узлов (Node) в индексе:", len(index.docstore.docs))

    query_engine = index.as_query_engine(similarity_top_k=2)

    question = "Сколько времени действует доступ на запись к продуктивной базе данных?"
    print(f"\nВопрос: {question}")

    t0 = time.time()
    response = query_engine.query(question)
    elapsed = time.time() - t0

    print(f"Ответ ({elapsed:.2f} с): {response}")

    print("\nИсточники, которые ушли в контекст LLM (Retrieval):")
    for node_with_score in response.source_nodes:
        title = node_with_score.node.metadata.get("title")
        print(f"  score={node_with_score.score:.4f}  [{title}]  {node_with_score.node.get_content()[:70]!r}")


if __name__ == "__main__":
    main()
