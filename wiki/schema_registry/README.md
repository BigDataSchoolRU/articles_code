# Schema Registry

Код к Wiki-статье «Schema Registry» на сайте BigDataSchool: https://bigdataschool.ru/wiki/schema_registry/

## Состав
- `docker-compose.yml` — Apache Kafka 4.3.0 в режиме KRaft и Confluent Schema Registry 8.3.1
- `compat_check.sh` — регистрация схемы и проверка совместимости через REST API реестра
- `avro_roundtrip.py` — сериализация Avro, разбор пятибайтового префикса, чтение сообщения обратно
- `RUNBOOK.md` — пошаговый прогон с проверками

## Окружение
Docker с поддержкой Compose, Python 3.12 и пакет confluent-kafka 2.15.0 с дополнениями avro
и schemaregistry. Свободные порты 9092 и 8081.

## Как запустить
1. `docker compose up -d`, дождаться ответа `curl http://localhost:8081/subjects`
2. `./compat_check.sh`
3. `python3 avro_roundtrip.py`
4. `docker compose down` после прогона
