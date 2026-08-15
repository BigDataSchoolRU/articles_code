# RUNBOOK: демо Kafka Connect на Apache Kafka 4.3.0

Прогон поднимает брокер Kafka в режиме KRaft и один worker Kafka Connect в distributed-режиме,
запускает на них пару коннекторов FileStream и показывает, где Connect хранит состояние.

## Окружение

- Docker Desktop 29.4.2, Docker Compose 5.1.3
- Образ `apache/kafka:4.3.0` (в нём есть и брокер, и скрипты Connect)
- Порт 8083 свободен, он отдаётся REST API worker
- Все команды запускаются из папки с `docker-compose.yml`

## Шаг 1. Поднять брокер и worker

```
docker compose up -d
curl -s http://localhost:8083/
```

Ожидаемо: ответ вида `{"version":"4.3.0","commit":"...","kafka_cluster_id":"..."}`. Worker
поднимается дольше брокера, первые 20-30 секунд curl может не отвечать, это нормально.

Шаг прошёл, если версия в ответе совпадает с версией образа.

## Шаг 2. Посмотреть список плагинов

```
curl -s http://localhost:8083/connector-plugins
```

Ожидаемо: FileStreamSinkConnector, FileStreamSourceConnector и три коннектора MirrorMaker.
Это всё, что приезжает в дистрибутиве Apache Kafka, сторонние плагины ставятся отдельно.

Шаг прошёл, если в списке есть оба класса FileStream.

## Шаг 3. Создать топик

```
docker exec kc_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 \
  --create --topic demo_orders --partitions 3 --replication-factor 1
```

Ожидаемо: `Created topic demo_orders.` Три партиции нужны, чтобы дальше увидеть, чем
ограничен параллелизм sink-коннектора.

## Шаг 4. Запустить source-коннектор

```
printf 'order-1001;paid;1990\norder-1002;paid;450\norder-1003;cancelled;0\n' > data/orders.txt
curl -s -X POST -H "Content-Type: application/json" \
  --data @connectors/file_source.json http://localhost:8083/connectors
curl -s http://localhost:8083/connectors/orders-file-source/status
```

Ожидаемо: коннектор в состоянии RUNNING и ровно один task, хотя в конфигурации стоит
`tasks.max: 3`. Так и должно быть: FileStreamSource не умеет делить один файл на части.

Шаг прошёл, если в топике оказались три строки:

```
docker exec kc_kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 \
  --topic demo_orders --from-beginning --max-messages 3 --timeout-ms 15000
```

## Шаг 5. Запустить sink-коннектор с преобразованиями

```
curl -s -X POST -H "Content-Type: application/json" \
  --data @connectors/file_sink.json http://localhost:8083/connectors
cat data/orders_out.txt
```

Ожидаемо: строки вида `Struct{line=order-1001;paid;1990,src=kafka-connect-demo}`. Плоская
строка обёрнута в структуру трансформацией HoistField, поле `src` добавлено InsertField.

Шаг прошёл, если в файле приёмника появились все строки и у каждой есть поле `src`.

## Шаг 6. Посмотреть, сколько task реально работает

```
curl -s http://localhost:8083/connectors/orders-file-sink/status
docker exec kc_kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --describe --group connect-orders-file-sink
```

Ожидаемо: пять task в состоянии RUNNING, но в группе потребителей партиции разобраны только
тремя из них. Лишние task живы и ничего не делают.

## Шаг 7. Найти состояние Connect в служебных топиках

```
docker exec kc_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --describe --topic connect-offsets
docker exec kc_kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 \
  --topic connect-offsets --from-beginning --formatter-property print.key=true \
  --max-messages 1 --timeout-ms 10000
```

Ожидаемо: топик с политикой `cleanup.policy=compact`, а внутри запись вида
`["orders-file-source",{"filename":"/data/orders.txt"}]  {"position":64}`. Это и есть позиция
чтения источника.

## Шаг 8. Перезапустить worker

```
printf 'order-1004;paid;7300\n' >> data/orders.txt
docker compose restart connect
curl -s http://localhost:8083/connectors
```

Ожидаемо: после перезапуска оба коннектора снова в списке, хотя их никто не создавал заново,
а в файле приёмника нет дублей. Конфигурация приехала из служебного топика, позиция чтения
оттуда же.

Шаг прошёл, если число строк в `data/orders_out.txt` равно числу строк в `data/orders.txt`.

## Если не так

- **REST API не отвечает.** Worker ещё стартует либо порт 8083 занят другим процессом.
  Смотреть `docker compose logs connect`.
- **Коннектор в состоянии FAILED.** Причина лежит в поле `trace` ответа
  `/connectors/<имя>/status`, чаще всего это опечатка в имени класса или недоступный файл.
- **В файле приёмника пусто.** Sink пишет пачками, подождите несколько секунд. Если пусто и
  дальше, проверьте, что имя топика в конфигурации sink совпадает с топиком source.
- **Пустой список плагинов FileStream.** Значение `plugin.path` должно указывать на файл
  `connect-file-<версия>.jar` вашей версии Kafka.

## Прибраться

```
docker compose down -v
```
