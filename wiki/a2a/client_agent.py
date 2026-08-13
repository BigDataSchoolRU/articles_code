# a2a-sdk 1.1.2 (протокол A2A 1.0), Python 3.12.13, прогон против course_agent.py
"""Клиентский агент A2A: находит удалённого агента по Agent Card и делегирует ему задачу."""

import asyncio

import httpx

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_stream_response_text, new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

AGENT_BASE_URL = "http://127.0.0.1:41241"
QUESTION = "Про что курс AGENT и сколько он длится?"


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as http:
        # Шаг 1. Discovery: карточка агента лежит по well-known адресу
        # /.well-known/agent-card.json, скачивается обычным GET-запросом.
        resolver = A2ACardResolver(httpx_client=http, base_url=AGENT_BASE_URL)
        card = await resolver.get_agent_card()

        print("=== Agent Card ===")
        print("name:", card.name)
        print("version:", card.version)
        for iface in card.supported_interfaces:
            print("interface:", iface.protocol_binding, iface.url)
        print("streaming:", card.capabilities.streaming)
        for skill in card.skills:
            print("skill:", skill.id, "|", skill.name)

        # Шаг 2. Клиент собирается по карточке: транспорт и адрес берутся из неё,
        # руками URL метода никто не склеивает.
        client = await create_client(card, ClientConfig(httpx_client=http))

        # Шаг 3. Отправка сообщения. Ответом приходит поток событий: сначала Task,
        # затем обновления статуса и артефакты.
        request = SendMessageRequest(
            message=new_text_message(QUESTION, role=Role.ROLE_USER)
        )
        print("\n=== Поток событий ===")
        answer = ""
        async for chunk in client.send_message(request):
            if chunk.HasField("task"):
                print(f"task: id={chunk.task.id} state={TaskState.Name(chunk.task.status.state)}")
            elif chunk.HasField("status_update"):
                state = TaskState.Name(chunk.status_update.status.state)
                print(f"status_update: {state} | {get_stream_response_text(chunk)}")
            elif chunk.HasField("artifact_update"):
                answer = get_stream_response_text(chunk)
                print(f"artifact_update: name={chunk.artifact_update.artifact.name}")
            elif chunk.HasField("message"):
                print("message:", get_stream_response_text(chunk))

        print("\n=== Ответ удалённого агента ===")
        print(answer)


if __name__ == "__main__":
    asyncio.run(main())
