# a2a-sdk 1.1.2 (протокол A2A 1.0), Python 3.12.13, Ollama 0.32.9, модель qwen2.5:7b
"""Удалённый агент A2A: отвечает на вопросы по курсам BigDataSchool.

Публикует Agent Card по адресу /.well-known/agent-card.json и обслуживает
JSON-RPC биндинг протокола A2A на /a2a/jsonrpc/.
"""

import uvicorn
from ollama import AsyncClient
from starlette.applications import Starlette

from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_artifact_update_event,
    new_text_status_update_event,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    TaskState,
)

HOST = "127.0.0.1"
PORT = 41241
MODEL = "qwen2.5:7b"

# Мини-каталог, который агент держит у себя. Клиентскому агенту он не виден:
# в A2A удалённый агент остаётся чёрным ящиком.
CATALOG = """
AGENT - ИИ-агенты для оптимизации бизнес-процессов, 2 дня, про агентные системы и LLM.
MLOPS - Разработка и внедрение ML-решений, 3 дня, про промышленный цикл ML.
KAFKA - Apache Kafka: администрирование кластера, 3 дня, про эксплуатацию брокера.
"""

SYSTEM_PROMPT = (
    "Ты консультант учебного центра. Отвечай строго по каталогу ниже, "
    "на русском языке, одним абзацем не длиннее 40 слов. "
    "Если курса в каталоге нет, так и скажи.\nКаталог:" + CATALOG
)

# Agent Card: паспорт агента, по которому клиент понимает, что агент умеет
# и куда стучаться. В версии 1.0 адрес живёт в supported_interfaces.
AGENT_CARD = AgentCard(
    name="BigDataSchool Course Agent",
    description="Консультирует по курсам учебного центра BigDataSchool",
    version="1.0.0",
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            protocol_version="1.0",
            url=f"http://{HOST}:{PORT}/a2a/jsonrpc/",
        )
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="course_info",
            name="Справка по курсу",
            description="Отвечает, о чём курс и сколько он длится",
            tags=["курсы", "обучение"],
            examples=["Про что курс AGENT?", "Сколько длится MLOPS?"],
        )
    ],
)


class CourseAgentExecutor(AgentExecutor):
    """Исполнитель задачи: переводит запрос A2A в вызов локальной LLM."""

    def __init__(self) -> None:
        self._llm = AsyncClient()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Шаг 1. Заводим Task. По правилам A2A 1.0 объект Task обязан уйти
        # в очередь событий первым, иначе SDK бросит InvalidAgentResponseError.
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        # Шаг 2. Сообщаем клиенту, что взяли работу в обработку.
        await event_queue.enqueue_event(
            new_text_status_update_event(
                task_id=task.id,
                context_id=task.context_id,
                state=TaskState.TASK_STATE_WORKING,
                text="Смотрю каталог курсов",
            )
        )

        # Шаг 3. Собственно работа. Что тут внутри, клиенту знать не нужно.
        question = get_message_text(context.message)
        response = await self._llm.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            options={"temperature": 0.1},
        )
        answer = response["message"]["content"].strip()

        # Шаг 4. Результат работы уезжает артефактом, а не просто текстом
        # в чате: артефакт привязан к задаче и его можно запросить позже.
        await event_queue.enqueue_event(
            new_text_artifact_update_event(
                task_id=task.id,
                context_id=task.context_id,
                name="course_answer",
                text=answer,
                last_chunk=True,
            )
        )

        # Шаг 5. Терминальное состояние закрывает жизненный цикл задачи.
        await event_queue.enqueue_event(
            new_text_status_update_event(
                task_id=task.id,
                context_id=task.context_id,
                state=TaskState.TASK_STATE_COMPLETED,
                text="Готово",
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Отмена в демо не поддержана: спецификация разрешает вернуть ошибку.
        raise NotImplementedError("Отмена задачи в этом агенте не реализована")


def build_app() -> Starlette:
    handler = DefaultRequestHandler(
        agent_executor=CourseAgentExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=AGENT_CARD,
    )
    routes = create_agent_card_routes(AGENT_CARD)
    routes += create_jsonrpc_routes(handler, rpc_url="/a2a/jsonrpc/")
    return Starlette(routes=routes)


if __name__ == "__main__":
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="warning")
