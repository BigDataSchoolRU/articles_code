# RUNBOOK: Stream Processing — минимальный процессор с watermark и чекпоинтингом

## Окружение

- Docker с брокером Kafka в режиме KRaft (без ZooKeeper), образ `apache/kafka:4.3.0`, один узел
  совмещает роли брокера и контроллера, порт `9092`, автосоздание топиков выключено.
- Python 3.12, пакет `confluent-kafka` 2.15.0.
- Никакого реестра схем, GPU или LLM не требуется — демо полностью на CPU без внешних моделей.

Замените `localhost:9092` на свой адрес брокера, если Kafka поднята не локально.

## Шаг 1. Поднять Kafka

```yaml
# docker-compose.yml
services:
  kafka:
    image: apache/kafka:4.3.0
    container_name: kafka
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@localhost:9093
      KAFKA_LISTENERS: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"
```

```bash
docker compose up -d
```

Что должно быть в выводе: контейнер `kafka` в статусе `Up`. Проверка:

```bash
docker exec kafka /opt/kafka/bin/kafka-topics.sh --list --bootstrap-server localhost:9092
```

Пустой список без ошибки означает, что брокер отвечает.

## Шаг 2. Создать топик

Автосоздание выключено намеренно — топик с одним партиционом делает демо детерминированным
(один процессор = один глобальный watermark, без слияния watermark между партициями).

```bash
docker exec kafka /opt/kafka/bin/kafka-topics.sh \
  --create --topic stream_processing_events \
  --bootstrap-server localhost:9092 \
  --partitions 1 --replication-factor 1
```

Что должно быть в выводе: `Created topic stream_processing_events.`

## Шаг 3. Установить зависимости

```bash
python3 -m venv .venv
./.venv/bin/pip install confluent-kafka==2.15.0
```

## Шаг 4. Отправить события не по порядку

```bash
./.venv/bin/python3 producer.py
```

Что должно быть в выводе: `отправлено 14 событий в 'stream_processing_events' за N с`. Список
событий в файле специально не отсортирован по времени события — так демонстрируется, что
tumbling-окно и watermark работают по event time, а не по порядку прихода в топик.

## Шаг 5. Запустить процессор

```bash
./.venv/bin/python3 processor.py
```

Что должно быть в выводе: строки `[emit] sensor=... window=[...) count=... avg=...
watermark=...` по мере закрытия окон, и одна-две строки `[late-drop] ...` — это события, чьё
окно watermark уже закрыл к моменту их прихода. В конце строка `итого: обработано=14, ...`.
Как понять, что шаг прошёл: `окон осталось открытыми=0` после финального флаша.

## Шаг 6. Демонстрация восстановления после падения

Процессор пишет чекпоинт (`checkpoint.json`) на диск после каждого сообщения. Если процесс
реально убить (`Ctrl+C` или `kill -9` в середине обработки) и запустить `processor.py` заново,
он продолжит с сохранённого offset и состояния окон, не пересчитывая уже закрытые окна.

Для воспроизводимой демонстрации без ручного `kill` в коде есть флаг `--crash-after`,
имитирующий падение после N обработанных сообщений:

```bash
rm -f checkpoint.json
./.venv/bin/python3 processor.py --crash-after 8   # упадёт намеренно, код возврата 1
cat checkpoint.json                                # чекпоинт на диске
./.venv/bin/python3 processor.py                    # продолжит с offset=8 до конца
```

Что должно быть в выводе второго запуска: строка `восстановление из чекпоинта: offset=8,
watermark=10, обработано ранее=8`, дальше обработка оставшихся событий без повторного
появления окон `[0,10)`, которые уже были закрыты и напечатаны в первом запуске.

## Если не так

- **`UNKNOWN_TOPIC_OR_PARTITION` у producer/consumer.** Автосоздание топиков выключено — топик
  из шага 2 не создан. Повторить шаг 2.
- **Процессор читает события с начала топика повторно.** `checkpoint.json` не удалён между
  независимыми прогонами — процессор доверяет offset из чекпоинта и продолжает с него, а не с
  начала. Для чистого повторного прогона: `rm -f checkpoint.json` и пересоздать топик (шаг 2).
- **Нет вывода от процессора вообще.** Проверить, что producer отработал раньше и брокер
  доступен: `docker exec kafka /opt/kafka/bin/kafka-topics.sh --describe --topic
  stream_processing_events --bootstrap-server localhost:9092` должен показать непустой топик.
- **`[late-drop]` для события, которое кажется не опоздавшим.** Опоздание считается не от
  текущего времени часов, а от максимального `event_time`, уже увиденного процессором:
  watermark = max(event_time) − 5 секунд. Если окно события уже закрыто по этой формуле, оно
  дропается независимо от того, что событие пришло в топик быстро.
