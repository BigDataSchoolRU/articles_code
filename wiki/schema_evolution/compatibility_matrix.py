# confluentinc/cp-schema-registry 8.3.1, Docker образ, прогнано на стенде 2026-09-05
# REST API v1, requests 2.34.2
#
# Регистрирует базовую схему заказа, затем прогоняет набор типовых изменений через
# эндпоинт /compatibility под каждым из трёх режимов (BACKWARD, FORWARD, FULL) и печатает
# матрицу pass/fail. Реестр меняет режим глобально на время своей проверки — это ограничение
# самого REST API v1, отдельного per-request параметра режима нет.

import json

import requests

SR = "http://localhost:8081"
CT = {"Content-Type": "application/vnd.schemaregistry.v1+json"}
SUBJECT = "schema_evolution_order-value"

# базовая схема: заказ с идентификатором и суммой
schema_v1 = {
    "type": "record",
    "name": "Order",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "amount", "type": "double"},
    ],
}

# кандидаты на изменение схемы: имя, схема-кандидат
CHANGES = [
    (
        "поле добавлено с default",
        {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "amount", "type": "double"},
                {"name": "currency", "type": "string", "default": "RUB"},
            ],
        },
    ),
    (
        "поле добавлено без default",
        {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "amount", "type": "double"},
                {"name": "currency", "type": "string"},
            ],
        },
    ),
    (
        "поле удалено",
        {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "id", "type": "string"},
            ],
        },
    ),
    (
        "поле переименовано без alias",
        {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "total", "type": "double"},
            ],
        },
    ),
    (
        "тип сужен double -> int",
        {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "amount", "type": "int"},
            ],
        },
    ),
    (
        "тип расширен double -> string",
        {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "amount", "type": "string"},
            ],
        },
    ),
]

MODES = ["BACKWARD", "FORWARD", "FULL"]


def reset_subject():
    """Удаляет subject от прошлого прогона: мягкое удаление, затем окончательное."""
    requests.delete(f"{SR}/subjects/{SUBJECT}")
    requests.delete(f"{SR}/subjects/{SUBJECT}?permanent=true")


def register_v1():
    resp = requests.post(
        f"{SR}/subjects/{SUBJECT}/versions",
        headers=CT,
        data=json.dumps({"schemaType": "AVRO", "schema": json.dumps(schema_v1)}),
    )
    resp.raise_for_status()
    print(f"зарегистрирована схема v1: {resp.json()}")


def set_subject_mode(mode: str):
    resp = requests.put(
        f"{SR}/config/{SUBJECT}",
        headers=CT,
        data=json.dumps({"compatibility": mode}),
    )
    resp.raise_for_status()


def check_compatibility(candidate_schema: dict) -> bool:
    resp = requests.post(
        f"{SR}/compatibility/subjects/{SUBJECT}/versions/latest",
        headers=CT,
        data=json.dumps({"schemaType": "AVRO", "schema": json.dumps(candidate_schema)}),
    )
    resp.raise_for_status()
    return resp.json()["is_compatible"]


def build_matrix():
    reset_subject()
    register_v1()

    matrix = {}
    for mode in MODES:
        set_subject_mode(mode)
        print(f"\nрежим subject выставлен: {mode}")
        matrix[mode] = {}
        for name, candidate in CHANGES:
            ok = check_compatibility(candidate)
            matrix[mode][name] = ok
            print(f"  {mode:8} | {name:32} | {'PASS' if ok else 'FAIL'}")

    return matrix


def print_table(matrix: dict):
    print("\n=== Матрица совместимости ===")
    name_width = max(len(name) for name, _ in CHANGES)
    header = "изменение".ljust(name_width) + "".join(f" | {m:8}" for m in MODES)
    print(header)
    print("-" * len(header))
    for name, _ in CHANGES:
        row = name.ljust(name_width)
        for mode in MODES:
            row += f" | {'PASS' if matrix[mode][name] else 'FAIL':8}"
        print(row)


if __name__ == "__main__":
    result = build_matrix()
    print_table(result)
