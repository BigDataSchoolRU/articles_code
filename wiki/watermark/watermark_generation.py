# PyFlink (apache-flink) 2.3.0, apache-beam 2.61.0, py4j 0.10.9.7, JDK 17.0.19 (Homebrew
# openjdk@17), коннектор flink-sql-connector-kafka-5.0.0-2.2.jar (для Flink 2.1/2.2, но
# рабочий и на Flink 2.3.0 - совместимость подтверждена прогоном на стенде), брокер
# apache/kafka:4.3.0 (KRaft), прогнано на стенде 2026-09-05.
#
# Демонстрирует три компонента из документации Flink (generating_watermarks):
# TimestampAssigner - достаёт event time из полезной нагрузки Kafka-сообщения;
# WatermarkGenerator - встроенная периодическая стратегия bounded-out-of-orderness;
# WatermarkStrategy - связывает первые два и добавляет idle-detection.
#
# Топик watermark_events создан с 2 партициями (см. RUNBOOK). Ключ Kafka-сообщения - это
# sensor_id, поэтому каждый датчик попадает в одну и ту же партицию стабильно. sensor-2
# в этом сценарии перестаёт слать события на середине прогона - его партиция замолкает.
# Без пометки простаивающего источника (with_idleness) общий watermark равен минимуму по
# всем партициям (см. документацию Flink и research-файл, п.3) и навсегда застревает на
# минимальном значении, потому что молчащая партиция никогда не продвигает свой watermark
# дальше. Проверено прогоном без with_idleness на этом стенде: ни один таймер и ни одно
# окно не сработали за 12+ секунд, хотя sensor-1 присылал события всё это время. Здесь
# with_idleness включён, чтобы демонстрировать рабочую, а не сломанную конфигурацию.
import json
import threading
import time

from pyflink.common import Duration, Time, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import ProcessWindowFunction, StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import KafkaOffsetsInitializer, KafkaSource
from pyflink.datastream.window import TumblingEventTimeWindows

BOOTSTRAP_SERVERS = "localhost:9094"
TOPIC = "watermark_events"
KAFKA_CONNECTOR_JAR = (
    "file://" + __file__.rsplit("/", 1)[0] + "/jars/flink-sql-connector-kafka-5.0.0-2.2.jar"
)
WINDOW_SECONDS = 4
OUT_OF_ORDERNESS_MS = 1000
IDLE_TIMEOUT_S = 3

START = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - START:6.1f}s] {msg}", flush=True)


class ExtractEventTime(TimestampAssigner):
    """K3 архитектуры: TimestampAssigner. Достаёт event time из JSON-поля 'ts' (мс)."""

    def extract_timestamp(self, value, record_timestamp):
        return json.loads(value)["ts"]


class PrintWindowResult(ProcessWindowFunction):
    """Печатает границы окна, watermark в момент срабатывания и агрегат по датчику."""

    def process(self, key, context, elements):
        rows = [json.loads(e) for e in elements]
        window = context.window()
        values = [r["value"] for r in rows]
        log(
            f"WINDOW FIRED sensor={key} range=[{window.start},{window.end}) "
            f"watermark={context.current_watermark()} n={len(values)} "
            f"avg={sum(values) / len(values):.2f}"
        )
        yield (key, window.start, window.end, len(values), sum(values) / len(values))


def produce_events():
    """Отдельный поток-продюсер: sensor-1 шлёт события всю дорогу, sensor-2 замолкает
    после трёх сообщений - это и есть простаивающий источник, который проверяет with_idleness."""
    time.sleep(2)  # дать Flink-джобе время подписаться (starting_offsets=latest)
    from confluent_kafka import Producer

    producer = Producer({"bootstrap.servers": BOOTSTRAP_SERVERS})
    base = int(time.time() * 1000)

    def send(sensor, offset_ms, value):
        ts = base + offset_ms
        payload = json.dumps({"sensor": sensor, "ts": ts, "value": value}).encode()
        producer.produce(TOPIC, key=sensor.encode(), value=payload)
        producer.flush(5)
        log(f"produced sensor={sensor} ts_offset={offset_ms} value={value}")

    for i in range(11):
        send("sensor-1", i * 1000, float(20 + i))
        if i < 3:
            send("sensor-2", i * 1000, float(100 + i))
        time.sleep(1.0)
    log("producer done")


def main():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.add_jars(KAFKA_CONNECTOR_JAR)
    env.set_parallelism(1)

    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(BOOTSTRAP_SERVERS)
        .set_topics(TOPIC)
        .set_group_id("watermark_generation_demo")
        .set_starting_offsets(KafkaOffsetsInitializer.latest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    strategy = (
        WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_millis(OUT_OF_ORDERNESS_MS))
        .with_timestamp_assigner(ExtractEventTime())
        .with_idleness(Duration.of_seconds(IDLE_TIMEOUT_S))
    )

    stream = env.from_source(source, strategy, "kafka-watermark-events")
    (
        stream.key_by(lambda v: json.loads(v)["sensor"])
        .window(TumblingEventTimeWindows.of(Time.seconds(WINDOW_SECONDS)))
        .process(PrintWindowResult())
    )

    producer_thread = threading.Thread(target=produce_events, daemon=True)
    producer_thread.start()

    job_client = env.execute_async("watermark generation demo")
    producer_thread.join()
    time.sleep(6)  # дать последним окнам сработать после того, как watermark догонит их
    job_client.cancel()
    log("job cancelled, demo finished")


if __name__ == "__main__":
    main()
