# Exactly-Once Semantics: демо к статье

Код к статье «Семантика Exactly-Once (Exactly-Once Semantics)»:
https://bigdataschool.ru/wiki/exactly_once_semantics/

Демо показывает две опоры exactly-once в Kafka: идемпотентный producer не создаёт дубль при
реальном ретрае на уровне протокола, а consumer с `isolation.level=read_committed` не видит
записи из отменённой транзакции, хотя они физически лежат в логе.

## Файлы

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | один брокер Apache Kafka 4.3.0 в режиме KRaft, порт 9092 |
| `idempotent_producer.py` | замораживает брокер на время отправки и показывает, что ретрай не даёт дубль |
| `transactional_producer.py` | коммитит одну транзакцию, откатывает другую, читает лог с разным `isolation.level` |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Docker с плагином Compose, Python 3.12, `confluent-kafka` 2.15.0. Прогнано на macOS 26.5.2
(arm64), Docker 29.7.2, Kafka 4.3.0.

## Как запустить

```bash
python3 -m pip install confluent-kafka==2.15.0
docker compose up -d
docker exec exactly_once_semantics_kafka /opt/kafka/bin/kafka-topics.sh --create \
  --bootstrap-server localhost:9092 \
  --topic exactly_once_semantics_events --partitions 3 --replication-factor 1
python3 idempotent_producer.py
python3 transactional_producer.py
docker compose down
```

Подробности по шагам и разбор вывода в `RUNBOOK.md`.
