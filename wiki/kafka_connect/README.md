# Kafka Connect

Код к Wiki-статье «Kafka Connect» на сайте BigDataSchool: https://bigdataschool.ru/wiki/kafka_connect/

## Состав

- `docker-compose.yml` — брокер Apache Kafka 4.3.0 в режиме KRaft и worker Kafka Connect в distributed-режиме
- `connect-distributed.properties` — конфигурация worker: служебные топики, конвертеры, REST-порт, plugin.path
- `connectors/file_source.json` — конфигурация source-коннектора FileStreamSource
- `connectors/file_sink.json` — конфигурация sink-коннектора FileStreamSink с двумя SMT
- `RUNBOOK.md` — пошаговый прогон с проверками на каждом шаге

## Окружение

- Docker Desktop 29.4.2, Docker Compose 5.1.3
- Образ `apache/kafka:4.3.0`, других зависимостей нет
- Свободные порты: 8083 для REST API worker

## Как запустить

1. `docker compose up -d` и дождаться ответа от `curl http://localhost:8083/`
2. Создать топик `demo_orders` на три партиции
3. Отправить конфигурации коннекторов из папки `connectors` POST-запросами на `/connectors`
4. Проверять результат по `/connectors/<имя>/status` и по файлу `data/orders_out.txt`

Подробный порядок с ожидаемым выводом каждого шага лежит в `RUNBOOK.md`.
