# RUNBOOK: Watermark в PyFlink

Демо на PyFlink (DataStream API) показывает, как Flink генерирует watermark по событиям из
Kafka и как он влияет на закрытие оконных агрегаций и обработку опоздавших событий.

## Окружение

- Java 17 (JDK), например Temurin/OpenJDK 17.x
- Python 3.12 в отдельном virtualenv, **не смешивайте с другими проектами** — у PyFlink
  тяжёлое дерево зависимостей (apache-beam, pandas, pyarrow, protobuf конкретных версий),
  которое конфликтует с современными пакетами
- Docker (для локального Kafka)
- Пакеты в virtualenv: `apache-flink==2.3.0`, `confluent-kafka==2.15.0`
- Коннектор `flink-sql-connector-kafka` — jar-файл, скачивается вручную (см. ниже),
  автоматически с `pip install apache-flink` не ставится

Все адреса ниже — `localhost`, поднимаемые вами самими контейнеры.

## Шаг 1. Виртуальное окружение

apache-flink тянет apache-beam, который на новых версиях setuptools (>=81, там убрали
`pkg_resources`) не собирается из исходников. Ставьте в **чистый, отдельный** venv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install "setuptools<81" wheel
pip install --no-build-isolation apache-flink==2.3.0 confluent-kafka==2.15.0
```

Проверка:

```bash
python3 -c "import pyflink; print(pyflink.__file__)"
```

Должен напечататься путь внутри вашего venv без ошибок импорта.

## Шаг 2. Java

PyFlink запускает JVM через Py4J и требует Java 17+ в `JAVA_HOME`:

```bash
export JAVA_HOME=/путь/к/jdk-17   # например /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export PATH="$JAVA_HOME/bin:$PATH"
java -version
```

В выводе должна быть строка `openjdk version "17...`. Без явного `JAVA_HOME` PyFlink падает
с `RuntimeError: Java gateway process exited before sending its port number` и невнятным
`Unable to locate a Java Runtime` в stderr — это ошибка про Java, а не про сам PyFlink.

## Шаг 3. Kafka-коннектор для Flink

Готового jar под Flink 2.3.0 на Maven Central на момент написания статьи нет — берите
ближайшую опубликованную версию линейки 2.x, она совместима:

```bash
mkdir -p jars
curl -fsSL -o jars/flink-sql-connector-kafka-5.0.0-2.2.jar \
  "https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/5.0.0-2.2/flink-sql-connector-kafka-5.0.0-2.2.jar"
```

Совместимость версии 5.0.0-2.2 (собрана под Flink 2.2) с рантаймом Flink 2.3.0 проверена
прямым прогоном на этом стенде — коннектор подключается и читает без ошибок.

## Шаг 4. Kafka

```bash
docker compose up -d
```

Ожидаемо: контейнер `watermark_kafka` в статусе `Up`. Проверка готовности:

```bash
docker exec watermark_kafka /opt/kafka/bin/kafka-topics.sh --list --bootstrap-server localhost:9092
```

Пустой список без ошибки — брокер готов. Создайте топик на **2 партиции** (это важно для
`watermark_generation.py` — демо показывает, как простаивающая партиция блокирует общий
watermark):

```bash
docker exec watermark_kafka /opt/kafka/bin/kafka-topics.sh --create \
  --topic watermark_events --bootstrap-server localhost:9092 \
  --partitions 2 --replication-factor 1
```

## Шаг 5. Запуск демо

```bash
source .venv/bin/activate
export JAVA_HOME=/путь/к/jdk-17
export PATH="$JAVA_HOME/bin:$PATH"

python3 watermark_generation.py
```

Оба файла — самостоятельные PyFlink-джобы: внутри поднимается `KafkaSource`, а в фоновом
потоке того же процесса — продюсер на `confluent-kafka`, который публикует события с
реальными паузами между ними (это принципиально: watermark продвигается по мере
поступления данных, а не мгновенно, как было бы с уже готовым batch-датасетом). Джоба
слушает Kafka `latest`-офсетом, поэтому её нужно запускать **до** появления интересующих
вас сообщений — продюсер стартует с задержкой в 2 секунды, чтобы джоба успела
подписаться.

Ожидаемый вывод `watermark_generation.py`: строки `produced ...` вперемешку со строками
`WINDOW FIRED ...`, где для датчика `sensor-2` (который перестаёт слать события на
середине прогона) окно всё равно корректно закрывается — это и есть эффект
`with_idleness()`. Без него джоба зависла бы: ни одно окно не закрылось бы вообще, пока
идёт запись, — на этом стенде так и было проверено отдельно.

```bash
python3 late_event_handling.py
```

Ожидаемый вывод: строки `WINDOW key=... offsets=[...]` с корректным окном и watermark на
момент срабатывания. Скрипт запускает два сценария подряд (каждый — своя джоба): опоздание
в пределах `allowedLateness` и опоздание за его пределами. Полный прогон занимает около
полутора минут — большая часть времени это намеренные паузы, чтобы watermark успел
продвинуться по-настоящему, а не мгновенно на bounded-источнике (см. раздел «если не
так»).

Джобы не завершаются сами — это нормально для потоковой обработки: `env.execute_async()` +
`job_client.cancel()` в конце скрипта, эмулируя штатную остановку. В проде вместо
`cancel()` используют `stop --savepoint`.

## Если не так

- **`RuntimeError: Java gateway process exited before sending its port number` +
  `Unable to locate a Java Runtime`** — не установлен `JAVA_HOME` или он указывает не на
  JDK 17+. См. шаг 2.
- **`ModuleNotFoundError: No module named 'pkg_resources'` при установке apache-flink** —
  новый setuptools (>=81) убрал `pkg_resources`, от которого зависит сборка apache-beam из
  исходников. Ставьте `setuptools<81` до `apache-flink`, см. шаг 1.
- **`TypeError: Could not found the Java class 'org.apache.flink.connector.kafka.source.KafkaSource.builder'`**
  — не подключён коннектор Kafka. Добавьте `env.add_jars("file:///.../flink-sql-connector-kafka-....jar")`
  до создания `KafkaSource`, см. шаг 3.
- **Watermark не двигается вообще, ни одно окно не закрывается** — если в топике несколько
  партиций и хотя бы одна не получает новых сообщений, общий watermark равен минимуму по
  всем партициям (документированное поведение Flink) и застревает на значении простаивающей
  партиции. Добавьте `.with_idleness(Duration.of_seconds(N))` к `WatermarkStrategy`.
- **Окно срабатывает только один раз в самом конце, независимо от паузы между событиями** —
  типичный симптом bounded-источника (`env.from_collection`): весь датасет проходит через
  джобу за миллисекунды, периодический генератор watermark не успевает тикнуть ни разу, и
  единственный watermark, который джоба видит, — это финальный `Long.MAX_VALUE` при
  завершении источника. Чтобы увидеть watermark в развитии, источник должен быть
  действительно потоковым (как `KafkaSource` в этом демо) и получать данные с реальными
  паузами.
- **Опоздавшее событие для уже закрытого окна не появляется ни в основном выводе (late
  firing), ни в side output** — на этом стенде это воспроизвелось: код настроен по
  документированному API (`allowed_lateness` + `side_output_late_data` +
  `get_side_output`), но при повторной отправке события в уже сработавшее окно ни один из
  двух путей не сработал ни разу за несколько независимых прогонов. Похоже на ограничение
  моста PyFlink 2.3.0 между Python UDF и `WindowOperator`, а не на ошибку конфигурации —
  подробнее в самой статье.
