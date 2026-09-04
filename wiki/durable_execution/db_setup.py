# PostgreSQL 18.4 (Homebrew), psycopg 3.3.4, прогнано на стенде 2026-09-04
"""
Готовит демо-базу durable_execution_demo.

Свою служебную схему `dbos` (журнал workflow, шагов, восстановления) DBOS
создаёт и мигрирует сам при первом DBOS.launch() — сюда её добавлять не
нужно. Здесь создаётся только сама база и одна прикладная таблица
side_effects: каждый шаг демо-workflow пишет в неё строку как в единственный
источник правды о том, сколько раз реально выполнился побочный эффект.
Если бы шаг выполнился повторно после восстановления, здесь появилась бы
вторая строка — это и есть проверяемый признак нарушения exactly-once.

Скрипт идемпотентен: базу можно удалять, повторный запуск пересоздаёт её.
"""

import psycopg

DB_NAME = "durable_execution_demo"
ADMIN_DSN = "host=localhost port=5432 dbname=postgres user=techfriends"
DEMO_DSN = f"host=localhost port=5432 dbname={DB_NAME} user=techfriends"

DDL = """
CREATE TABLE side_effects (
    id          serial PRIMARY KEY,
    workflow_id text NOT NULL,
    step_name   text NOT NULL,
    order_id    text NOT NULL,
    executed_at timestamptz NOT NULL DEFAULT now()
);
"""


def main() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
        conn.execute(f"CREATE DATABASE {DB_NAME}")

    with psycopg.connect(DEMO_DSN, autocommit=True) as conn:
        conn.execute(DDL)

    print(f"база {DB_NAME} готова, таблица side_effects создана")


if __name__ == "__main__":
    main()
