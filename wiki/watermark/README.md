# Watermark

Код для статьи [Watermark в потоковой обработке данных](https://bigdataschool.ru/wiki/watermark/).

## Состав

- `watermark_generation.py` — генерация watermark (`TimestampAssigner` + встроенный
  bounded-out-of-orderness `WatermarkGenerator` + `WatermarkStrategy`), оконная агрегация
  по event time, эффект простаивающей Kafka-партиции и `with_idleness()`.
- `late_event_handling.py` — `allowedLateness` и `side_output_late_data` для событий,
  которые пришли позже, чем watermark уже прошёл конец их окна.
- `docker-compose.yml` — локальный одноброкерный Kafka (KRaft) для обоих демо.
- `jars/` — коннектор `flink-sql-connector-kafka` (скачивается по инструкции в RUNBOOK, в
  репозиторий не коммитится).

## Окружение

Python 3.12, `apache-flink==2.3.0`, `confluent-kafka==2.15.0`, Java 17, Docker.

## Запуск

Подробно — в [RUNBOOK.md](./RUNBOOK.md). Коротко:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install "setuptools<81" wheel
pip install --no-build-isolation apache-flink==2.3.0 confluent-kafka==2.15.0

mkdir -p jars
curl -fsSL -o jars/flink-sql-connector-kafka-5.0.0-2.2.jar \
  "https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/5.0.0-2.2/flink-sql-connector-kafka-5.0.0-2.2.jar"

docker compose up -d
docker exec watermark_kafka /opt/kafka/bin/kafka-topics.sh --create \
  --topic watermark_events --bootstrap-server localhost:9092 \
  --partitions 2 --replication-factor 1

export JAVA_HOME=/путь/к/jdk-17 && export PATH="$JAVA_HOME/bin:$PATH"
python3 watermark_generation.py
python3 late_event_handling.py
```
