# Real-Time Analytics: демо к статье

Код к статье «Аналитика в реальном времени (Real-Time Analytics)»:
https://bigdataschool.ru/wiki/real_time_analytics/

Демо измеряет задержку между моментом события и моментом, когда пересчитанный агрегат
становится доступен запросу: поток заказов идёт через Kafka, каждое событие сразу попадает в
DuckDB и участвует в агрегате по категориям.

## Файлы

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | один брокер Apache Kafka 4.3.0 в режиме KRaft, порт 9092 |
| `consumer_realtime.py` | создаёт топик, читает поток, пишет в DuckDB, печатает задержку событие → агрегат |
| `producer.py` | шлёт 30 событий заказов по одному с паузами, имитируя непрерывный поток |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом и типовыми граблями |

## Окружение

Docker с плагином Compose, Python 3.12, `confluent-kafka` 2.15.0, `duckdb` 1.5.5. Прогнано на
macOS 26.5.2 (arm64), Docker 29.7.2, Kafka 4.3.0.

## Как запустить

```bash
python3 -m pip install confluent-kafka==2.15.0 duckdb==1.5.5
docker compose up -d
python3 consumer_realtime.py   # первым, в отдельном терминале
python3 producer.py            # вторым, после строки "жду события"
docker compose down
```

Подробности по шагам, ожидаемый вывод и грабли — в `RUNBOOK.md`.
