# openmetadata-ingestion 2.0.0.0, стенд docker-compose (server+ingestion+elasticsearch) 2.0.0,
# прогнано на стенде 2026-08-27. Источник: PostgreSQL 18.4 (Homebrew), демо-база semantic_layer_demo.
"""
Реальное сканирование локальной PostgreSQL-базы конвейером ingestion framework OpenMetadata
и запись результата через sink metadata-rest в поднятый docker-compose стенд (localhost:8585).

Логин делается каждый прогон: OpenMetadata не хранит долгоживущий пароль в файле, JWT
получаем через /api/v1/users/login и используем как securityConfig.jwtToken воркфлоу.
"""
import sys

import requests
from metadata.workflow.metadata import MetadataWorkflow

OPENMETADATA_HOST = "http://localhost:8585/api"
ADMIN_EMAIL = "admin@open-metadata.org"
ADMIN_PASSWORD_B64 = "YWRtaW4="  # "admin" в base64 — так его ждёт /users/login

# Локальный Postgres на этой машине, доверительная аутентификация: пароль не проверяется,
# но пустую строку OpenMetadata-коннектор не принимает, поэтому кладём непустую заглушку.
SOURCE_DB = {
    "type": "postgres",
    "serviceName": "wiki_semantic_layer_demo",
    "serviceConnection": {
        "config": {
            "type": "Postgres",
            "username": "techfriends",
            "authType": {"password": "not-checked-trust-auth"},
            "hostPort": "localhost:5432",
            "database": "semantic_layer_demo",
        }
    },
    # schemaFilterPattern фильтрует схемы для ингеста, но живёт не в serviceConnection (это
    # поле там тоже есть, но реально не используется), а в sourceConfig.config — без него
    # коннектор по умолчанию заодно сканирует служебную information_schema (70+ системных
    # представлений вроде triggers, routines) и заливает их в каталог наравне с бизнес-таблицами.
    "sourceConfig": {
        "config": {
            "type": "DatabaseMetadata",
            "schemaFilterPattern": {"excludes": ["^information_schema$"]},
        }
    },
}


def get_jwt_token() -> str:
    resp = requests.post(
        f"{OPENMETADATA_HOST}/v1/users/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD_B64},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["accessToken"]


def build_config(jwt_token: str) -> dict:
    return {
        "source": SOURCE_DB,
        "sink": {"type": "metadata-rest", "config": {}},
        "workflowConfig": {
            "loggerLevel": "INFO",
            "openMetadataServerConfig": {
                "hostPort": OPENMETADATA_HOST,
                "authProvider": "openmetadata",
                "securityConfig": {"jwtToken": jwt_token},
            },
        },
    }


def main() -> int:
    token = get_jwt_token()
    print(f"JWT получен, длина {len(token)} символов")

    workflow_config = build_config(token)
    workflow = MetadataWorkflow.create(workflow_config)
    workflow.execute()
    workflow.print_status()
    workflow.stop()

    # raise_from_status падает исключением при любом сбое шага — так прогон честно
    # завершается ненулевым кодом, а не тихо проглатывает ошибку источника.
    workflow.raise_from_status()
    print("Ingestion metadata workflow завершён успешно")
    return 0


if __name__ == "__main__":
    sys.exit(main())
