# openmetadata-ingestion 2.0.0.0, стенд OpenMetadata server 2.0.0, MCP-эндпоинт (JSON-RPC,
# stateless, версия протокола 2025-11-25 по ответу initialize), прогнано на стенде 2026-08-27.
"""
Показывает разницу между двумя способами читать те же метаданные, полученные скриптом
ingest_postgres_metadata.py: классический REST API каталога и MCP Server, который в 2.0
идёт включённым по умолчанию как внутреннее приложение McpApplication (без действий в UI).

REST отдаёт сырой документ индекса. MCP-инструмент get_asset_context отдаёт уже собранный
markdown с ключами и ограничениями — то, что AI-агент может подставить в промпт без разбора
JSON. Это и есть разница между «каталог» и «context layer» из фокуса статьи.
"""
import json
import sys

import requests

OPENMETADATA_HOST = "http://localhost:8585"
ADMIN_EMAIL = "admin@open-metadata.org"
ADMIN_PASSWORD_B64 = "YWRtaW4="
TABLE_FQN = "wiki_semantic_layer_demo.semantic_layer_demo.public.orders"


def get_jwt_token() -> str:
    resp = requests.post(
        f"{OPENMETADATA_HOST}/api/v1/users/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD_B64},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["accessToken"]


def rest_search(token: str, query: str) -> dict:
    resp = requests.get(
        f"{OPENMETADATA_HOST}/api/v1/search/query",
        params={"q": query, "index": "table_search_index"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def mcp_call(token: str, request_id: int, method: str, params: dict) -> dict:
    resp = requests.post(
        f"{OPENMETADATA_HOST}/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    token = get_jwt_token()

    print("=== 1. Классический REST API каталога: search/query ===")
    hits = rest_search(token, "orders")["hits"]["hits"]
    print(f"Найдено документов: {len(hits)}")
    top = hits[0]["_source"]
    print(f"Верхний результат: {top['fullyQualifiedName']}, колонок: {len(top['columns'])}")
    print("Дальше это сырой JSON индекса — агенту пришлось бы самому доставать ключи,")
    print("primary key и типы колонок из вложенной структуры.\n")

    print("=== 2. MCP Server: initialize ===")
    init = mcp_call(
        token, 1, "initialize",
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "wiki-demo", "version": "1.0"}},
    )
    server_info = init["result"]["serverInfo"]
    print(f"Сервер: {server_info['name']} {server_info['version']}, "
          f"протокол {init['result']['protocolVersion']}\n")

    print("=== 3. MCP Server: tools/list ===")
    tools = mcp_call(token, 2, "tools/list", {})["result"]["tools"]
    print(f"Инструментов доступно: {len(tools)}")
    print(", ".join(t["name"] for t in tools) + "\n")

    print("=== 4. MCP Server: tools/call search_metadata (найти таблицу по имени) ===")
    search_result = mcp_call(
        token, 3, "tools/call",
        {"name": "search_metadata", "arguments": {"query": "orders", "entityType": "table"}},
    )
    search_payload = json.loads(search_result["result"]["content"][0]["text"])
    print(f"Найдено таблиц: {search_payload['totalFound']}, "
          f"первая: {search_payload['results'][0]['fullyQualifiedName']}\n")

    print("=== 5. MCP Server: tools/call get_asset_context (готовый контекст для промпта) ===")
    context_result = mcp_call(
        token, 4, "tools/call",
        {"name": "get_asset_context", "arguments": {"entityType": "table", "fqn": TABLE_FQN, "format": "markdown"}},
    )
    context_payload = json.loads(context_result["result"]["content"][0]["text"])
    print(context_payload["content"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
