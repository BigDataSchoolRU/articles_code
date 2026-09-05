# RUNBOOK: Schema Evolution

Демо к статье [Schema Evolution](https://bigdataschool.ru/wiki/schema_evolution/) на
bigdataschool.ru. Два независимых примера: чистый механизм Avro schema resolution без
инфраструктуры и матрица режимов совместимости против настоящего Confluent Schema Registry.

## Окружение

- Python 3.12+, пакеты `fastavro` (проверено на 1.12.2) и `requests` (проверено на 2.34.2)
- Docker и Docker Compose v2 (проверено на Docker 29.7.2, Compose v5.3.1) — только для второго
  демо
- Порты `9092` (Kafka) и `8081` (Schema Registry) должны быть свободны на хосте
- Все адреса ниже — `localhost`, подставлять свои не нужно

Установка Python-зависимостей:

```bash
pip install fastavro==1.12.2 requests==2.34.2
```

## Шаг 1. Механизм schema resolution (без Docker)

```bash
python3 schema_resolution_avro.py
```

Что должно быть в выводе: три блока «Сценарий N». В сценарии 1 читатель получает запись без
поля `status` (отброшено) и с полем `currency`, заполненным default-значением `RUB`. В сценарии
2 резолюция заканчивается ошибкой `SchemaResolutionError: No default value for field status in
Order`, это ожидаемый результат сценария, а не сбой прогона. В сценарии 3 поле `curr` получает
default `RUB`, а не значение `EUR`, которое лежало в данных под именем `currency`.

Как понять, что шаг прошёл: скрипт завершается кодом `0` (`echo $?` после запуска). Ошибка
`SchemaResolutionError` в тексте вывода — это часть демонстрации, а не признак провала.

## Шаг 2. Матрица совместимости (нужен Docker)

Поднять брокер Kafka и реестр схем:

```bash
docker compose up -d
```

Проверить готовность реестра (может занять несколько секунд после старта):

```bash
curl -s http://localhost:8081/subjects
```

Ожидаемый вывод: `[]` — пустой список subject'ов, реестр отвечает.

Прогнать матрицу:

```bash
python3 compatibility_matrix.py
```

Что должно быть в выводе: сначала подтверждение регистрации схемы v1 (JSON с полем `"id"`),
затем построчный лог проверок по каждому из режимов `BACKWARD`/`FORWARD`/`FULL`, в конце —
таблица `PASS`/`FAIL` 6 строк на 3 столбца. Первая строка таблицы (`поле добавлено с default`)
должна быть `PASS` во всех трёх режимах — это единственное изменение, совместимое всегда.

Погасить стенд:

```bash
docker compose down
```

## Если не так

- **`curl: (7) Failed to connect` на порту 8081** — реестр ещё не поднялся или контейнер упал.
  Проверить логи: `docker compose logs schema-registry`. Частая причина — Kafka ещё не готова
  принимать соединения, реестр перезапускается сам через `depends_on`, подождать 5-10 секунд.
- **`Address already in use` при `docker compose up`** — порт `9092` или `8081` занят другим
  процессом (например, уже поднятым Kafka-стендом другой статьи). Погасить конфликтующий стенд
  или изменить проброс портов в `docker-compose.yml`.
- **`compatibility_matrix.py` падает с `ConnectionError`** — реестр не поднят или ещё не готов,
  см. первый пункт.
- **Повторный запуск `compatibility_matrix.py` без ошибок subject уже существует** — скрипт сам
  удаляет subject от прошлого прогона перед стартом (`DELETE /subjects/...`), повторный запуск
  безопасен.
