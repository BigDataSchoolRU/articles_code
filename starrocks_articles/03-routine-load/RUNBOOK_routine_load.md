<!--
  Код к статье "Потоковая загрузка из Apache Kafka в StarRocks через Routine Load"
  из серии материалов по StarRocks, "Школа Больших Данных".
  Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-routine-load-kafka/
  Автор: Bigdataschool.ru   "Школа Больших Данных"
  Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
-->

# Runbook. Практика статьи 3. Потоковая загрузка Kafka в StarRocks через Routine Load

Пошаговый порядок выполнения практики на стенде. Каждый шаг снабжен проверкой, чтобы
не идти дальше вслепую. Идем сверху вниз.

Окружение:
- Kafka 3.9.2 (KRaft), брокеры 10.140.0.91:9092, 10.140.0.92:9092, 10.140.0.93:9092
- StarRocks 3.5.0 (allin1), база shop уже создана
- Python 3.12 на машине, откуда запускаем продюсер

Файлы практики лежат рядом: producer.py и routine_load.sql.

---

## Шаг 1. Проверяем, что StarRocks видит брокеры Kafka

Это главное предусловие и самая частая причина, почему Routine Load не читает ни одного
сообщения. BE-нода StarRocks должна дотягиваться до брокеров по сети. Если StarRocks в
контейнере, проверяем доступность именно изнутри контейнера, а не с хоста.

```bash
# проверка TCP-доступа к брокерам из контейнера StarRocks средствами bash
for ip in 10.140.0.91 10.140.0.92 10.140.0.93; do
  docker exec starrocks bash -c "timeout 3 bash -c '</dev/tcp/${ip}/9092' && echo ${ip}:9092 OK || echo ${ip}:9092 FAIL"
done
```

Все три строки должны показать OK. Если FAIL, дальше идти нет смысла, сначала чиним сеть:
пробрасываем маршрут или запускаем контейнер в нужной сети. На хосте доступ можно проверить
отдельно.

```bash
for ip in 10.140.0.91 10.140.0.92 10.140.0.93; do
  timeout 3 bash -c "</dev/tcp/${ip}/9092" && echo ${ip} OK || echo ${ip} FAIL
done
```

---

## Шаг 2. Создаем топик orders

Топик создаем на три партиции, чтобы показать параллельное чтение. Фактор репликации 3 по
числу брокеров.

```bash
# протестировано для Apache Kafka 3.9.2 (KRaft)
kafka-topics.sh --bootstrap-server 10.140.0.91:9092 \
  --create --topic orders --partitions 3 --replication-factor 3

# проверка
kafka-topics.sh --bootstrap-server 10.140.0.91:9092 --describe --topic orders
```

В выводе describe должно быть три партиции с назначенными лидерами и репликами.

---

## Шаг 3. Готовим Python-окружение и ставим kafka-python

В Ubuntu 24.04 системный pip запрещает ставить пакеты глобально, поэтому используем venv.

```bash
cd ~/article03            # каталог, куда положили producer.py
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install kafka-python
python3 -c "import kafka; print('kafka-python', kafka.__version__)"
```

---

## Шаг 4. Запускаем продюсер и убеждаемся, что события идут в топик

Запускаем генератор в отдельном терминале. Он пишет примерно 50 событий в секунду.

```bash
source .venv/bin/activate
python3 producer.py
# в выводе увидишь строки вида: отправлено 500 событий
```

В другом терминале подглядываем в топик штатным консьюмером Kafka. Берем пять сообщений и
выходим.

```bash
kafka-console-consumer.sh --bootstrap-server 10.140.0.91:9092 \
  --topic orders --from-beginning --max-messages 5
```

Должны увидеть JSON с вложенным объектом customer. Если сообщения идут, продюсер работает,
и можно оставить его крутиться.

---

## Шаг 5. Создаем целевую таблицу в StarRocks

Подключаемся к StarRocks по MySQL-протоколу и создаем таблицу в модели Primary Key. Она
дает нативный UPSERT, повтор события с тем же order_id обновит строку, а не задвоит.

```bash
mysql -h 127.0.0.1 -P 9030 -u root
```

```sql
USE shop;

CREATE TABLE orders_rt (
    order_id    BIGINT,
    customer_id BIGINT,
    region_id   INT,
    order_date  DATE,
    status      VARCHAR(16),
    amount      DECIMAL(10,2),
    event_time  DATETIME
) PRIMARY KEY(order_id)
DISTRIBUTED BY HASH(order_id) BUCKETS 16;
```

---

## Шаг 6. Создаем задачу Routine Load

Задача читает топик orders и пишет в orders_rt. JSONPaths мапят вложенные customer.id и
customer.region в плоские колонки. Порядок путей строго соответствует порядку в COLUMNS.

```sql
CREATE ROUTINE LOAD shop.orders_stream ON orders_rt
COLUMNS(order_id, customer_id, region_id, order_date, status, amount, event_time)
PROPERTIES (
    "format" = "json",
    "jsonpaths" = "[\"$.order_id\",\"$.customer.id\",\"$.customer.region\",\"$.order_date\",\"$.status\",\"$.amount\",\"$.event_time\"]",
    "desired_concurrent_number" = "3",
    "max_batch_interval" = "10",
    "max_error_number" = "100"
)
FROM KAFKA (
    "kafka_broker_list" = "10.140.0.91:9092,10.140.0.92:9092,10.140.0.93:9092",
    "kafka_topic" = "orders",
    "property.kafka_default_offsets" = "OFFSET_BEGINNING"
);
```

---

## Шаг 7. Мониторим задачу через SHOW ROUTINE LOAD

Сразу после создания смотрим статус. Ключевые поля: State, Progress и статистика.

```sql
SHOW ROUTINE LOAD FOR shop.orders_stream\G
```

Что проверять в выводе:
- State должно быть RUNNING. Если PAUSED, смотри Шаг 10.
- Progress показывает текущие смещения по каждой партиции, они должны расти.
- В блоке statistic поля loadedRows и receivedBytes должны увеличиваться от запроса к запросу.

Подзадачи по партициям видно отдельной командой.

```sql
SHOW ROUTINE LOAD TASK WHERE JobName = "orders_stream"\G
```

---

## Шаг 8. Проверяем, что данные реально едут в таблицу

Делаем несколько запросов подряд с паузой, число строк должно расти. Это и есть потоковая
загрузка в реальном времени.

```sql
SELECT count(*) FROM shop.orders_rt;
-- подожди 5 секунд, повтори, число должно увеличиться

SELECT * FROM shop.orders_rt ORDER BY event_time DESC LIMIT 10;
```

В последних строках увидишь свежие события с только что проставленным event_time.

---

## Шаг 9. Демонстрация UPSERT и устойчивости к схеме (по желанию)

UPSERT. Если продюсер пришлет событие с уже существующим order_id, строка обновится, а не
задвоится. Проверяется тем, что count по order_id остается уникальным.

```sql
SELECT count(*) AS rows_total, count(DISTINCT order_id) AS uniq_orders
FROM shop.orders_rt;
-- значения должны совпадать, дублей по order_id нет
```

Дрейф схемы. Добавь в make_event продюсера новое поле, например "channel": "web". Задача
продолжит работать, лишнее поле она проигнорирует, потому что его нет в jsonpaths. Останавливать
Routine Load для этого не нужно.

---

## Шаг 10. Что делать, если задача ушла в PAUSED

Слишком много битых сообщений в окне выборки переводят задачу в PAUSED. Причину смотрим в
том же SHOW ROUTINE LOAD.

```sql
SHOW ROUTINE LOAD FOR shop.orders_stream\G
-- смотри поля ReasonOfStateChanged и ErrorLogUrls
```

По ссылке из ErrorLogUrls лежит лог с отбракованными строками. Типичные причины: строка вместо
числа в amount, невалидный JSON. После того как источник поправлен или поднят лимит ошибок,
возобновляем.

```sql
RESUME ROUTINE LOAD FOR shop.orders_stream;
```

Смещения не теряются, чтение продолжится с последнего зафиксированного места.

---

## Шаг 11. Остановка и очистка

```sql
-- остановить задачу загрузки
STOP ROUTINE LOAD FOR shop.orders_stream;
```

```bash
# остановить продюсер: Ctrl+C в его терминале
# при необходимости удалить топик
kafka-topics.sh --bootstrap-server 10.140.0.91:9092 --delete --topic orders
```

```sql
-- при необходимости удалить таблицу
DROP TABLE shop.orders_rt;
```

---

## Чек-лист для скриншотов в статью

- SHOW ROUTINE LOAD со State RUNNING и растущим Progress (Шаг 7).
- Два последовательных SELECT count с разными числами, чтобы показать рост потока (Шаг 8).
- Свежие строки из orders_rt с event_time (Шаг 8).
