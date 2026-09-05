# Lambda Architecture

Код к статье [Lambda Architecture](https://bigdataschool.ru/wiki/lambda_architecture/).

## Состав

- `docker-compose.yml` — один брокер Apache Kafka 4.3.0 в режиме KRaft, порт 9092.
- `event_producer.py` — пишет события сразу в Kafka (speed layer) и в append-only
  мастер-датасет `master_dataset.jsonl` (batch layer). Два запуска: пакет 1
  («уже случившийся» трафик), пакет 2 (новые события уже после прогона batch layer).
- `batch_layer.py` — полный пересчёт представления по всему мастер-датасету на DuckDB,
  фиксирует watermark (последний учтённый момент времени).
- `speed_layer.py` — Kafka-консьюмер, считает дельту только по событиям новее watermark.
- `serving_layer.py` — объединяет batch_view и speed_view, сравнивает устаревший ответ
  только от batch layer с ответом serving layer и сверяет merge с честным пересчётом.
- `RUNBOOK.md` — как поднять окружение и прогнать демо самостоятельно.

## Окружение

- Docker с плагином Compose, образ `apache/kafka:4.3.0`.
- Python 3.12, `confluent-kafka` 2.15.0, `duckdb` 1.5.5.

## Запуск

```bash
python3 -m pip install confluent-kafka==2.15.0 duckdb==1.5.5
docker compose up -d
python3 event_producer.py 1
python3 batch_layer.py
python3 event_producer.py 2
python3 speed_layer.py
python3 serving_layer.py
docker compose down
```

Подробности, ожидаемый вывод и типовые грабли — в `RUNBOOK.md`.
