# Event Streaming: демо к статье

Код к статье «Потоковая передача событий (Event Streaming)»:
https://bigdataschool.ru/wiki/event_streaming/

Демо показывает, чем лог событий отличается от очереди: события остаются в топике после
чтения, каждая группа потребителей ведёт свою позицию, а историю можно прочитать заново.

## Файлы

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | один брокер Apache Kafka 4.3.0 в режиме KRaft, порт 9092 |
| `producer.py` | создаёт топик `orders` на три партиции и пишет 8 событий с ключами |
| `consumer_groups.py` | читает лог разными группами: независимость, оффсеты, replay, деление партиций |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Docker с плагином Compose, Python 3.12, `confluent-kafka` 2.15.0. Прогнано на macOS 26.5.2
(arm64), Docker 29.7.2, Kafka 4.3.0.

## Как запустить

```bash
python3 -m pip install confluent-kafka==2.15.0
docker compose up -d
python3 producer.py
python3 consumer_groups.py
docker compose down
```

Подробности по шагам и разбор вывода в `RUNBOOK.md`.
