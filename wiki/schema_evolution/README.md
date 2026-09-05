# Schema Evolution

Демо к Wiki-статье [Schema Evolution](https://bigdataschool.ru/wiki/schema_evolution/) на
bigdataschool.ru.

## Файлы

- `schema_resolution_avro.py` — механизм Avro schema resolution на fastavro: добавление поля
  с default, удаление поля, переименование без alias. Без Docker и реестра схем.
- `compatibility_matrix.py` — матрица режимов совместимости BACKWARD/FORWARD/FULL против
  настоящего Confluent Schema Registry через REST API.
- `docker-compose.yml` — Kafka 4.3.0 (KRaft) и Confluent Schema Registry 8.3.1 для второго демо.
- `RUNBOOK.md` — пошаговая инструкция для читателя.

## Окружение

Python 3.12+, `fastavro` 1.12.2, `requests` 2.34.2, Docker с Compose v2.

## Как запустить

```bash
pip install fastavro==1.12.2 requests==2.34.2
python3 schema_resolution_avro.py

docker compose up -d
python3 compatibility_matrix.py
docker compose down
```

Подробности и ожидаемый вывод каждого шага — в `RUNBOOK.md`.
