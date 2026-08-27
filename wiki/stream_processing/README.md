# Stream Processing: демо к статье

Код к статье «Потоковая обработка данных (Stream Processing)»:
https://bigdataschool.ru/wiki/stream_processing/

Демо — минимальный процессор с нуля (не обёртка вокруг Kafka Streams/Flink): продюсер шлёт
события не по порядку event time, процессор считает tumbling-агрегат по event time, закрывает
окно только после прохождения watermark, периодически сбрасывает состояние в файл и
восстанавливается из него после падения.

## Файлы

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | один брокер Apache Kafka 4.3.0 в режиме KRaft, порт 9092, автосоздание топиков выключено |
| `producer.py` | шлёт 14 событий трёх датчиков в топик `stream_processing_events`, часть событий намеренно не по порядку event time |
| `processor.py` | tumbling-окна по event time, watermark, дроп опоздавших, чекпоинт на диск, восстановление после падения (`--crash-after`) |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Docker с плагином Compose, Python 3.12, `confluent-kafka` 2.15.0. Прогнано на macOS 26.5.2
(arm64), Docker 29.7.2, Kafka 4.3.0.

## Как запустить

```bash
python3 -m pip install confluent-kafka==2.15.0
docker compose up -d
docker exec kafka /opt/kafka/bin/kafka-topics.sh \
  --create --topic stream_processing_events \
  --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1
python3 producer.py
python3 processor.py
docker compose down
```

Демонстрация восстановления после падения и разбор вывода — в `RUNBOOK.md`.
