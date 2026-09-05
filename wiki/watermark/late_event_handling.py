# PyFlink (apache-flink) 2.3.0, apache-beam 2.61.0, py4j 0.10.9.7, JDK 17.0.19 (Homebrew
# openjdk@17), коннектор flink-sql-connector-kafka-5.0.0-2.2.jar (для Flink 2.1/2.2, но
# рабочий и на Flink 2.3.0 - совместимость подтверждена прогоном на стенде), брокер
# apache/kafka:4.3.0 (KRaft), прогнано на стенде 2026-09-05.
#
# Демонстрирует allowedLateness и side output для событий, которые пришли позже, чем
# watermark уже продвинулся мимо конца их окна:
# - в пределах allowedLateness окно пересчитывается повторно (late firing);
# - за пределами allowedLateness событие уходит в side output через OutputTag, а не
#   теряется молча.
#
# "sensor-1" - единственный ключ, чьё окно мы наблюдаем. Второй ключ "clock" нужен только
# чтобы толкать общий watermark вперёд, не касаясь состояния окон "sensor-1": на этом
# стенде подтверждено прогоном, что искусственное "далёкое вперёд" событие ПОД ТЕМ ЖЕ
# ключом, что и наблюдаемое окно, иногда попадает в чужой elements при печати внутри
# ProcessWindowFunction, когда для одного ключа одновременно открыто больше одного окна -
# со своим ключом "clock" этого не происходит ни разу за серию прогонов. Это граница
# метода наблюдения, а не свойство watermark как такового.
import json
import threading
import time

from pyflink.common import Duration, Time, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.typeinfo import Types
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import ProcessFunction, ProcessWindowFunction, StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import KafkaOffsetsInitializer, KafkaSource
from pyflink.datastream.output_tag import OutputTag
from pyflink.datastream.window import TumblingEventTimeWindows

BOOTSTRAP_SERVERS = "localhost:9094"
TOPIC = "watermark_events"
KAFKA_CONNECTOR_JAR = (
    "file://" + __file__.rsplit("/", 1)[0] + "/jars/flink-sql-connector-kafka-5.0.0-2.2.jar"
)
WINDOW_SECONDS = 5
ALLOWED_LATENESS_MS = 4000
OUT_OF_ORDERNESS_MS = 500

START = time.time()
LATE_DATA_TAG = OutputTag("late-data", Types.STRING())


def log(msg: str) -> None:
    print(f"[{time.time() - START:6.1f}s] {msg}", flush=True)


class ExtractEventTime(TimestampAssigner):
    def extract_timestamp(self, value, record_timestamp):
        return json.loads(value)["ts"]


class PrintWindowResult(ProcessWindowFunction):
    """Основной выход окна. Late firing виден здесь же: то же окно печатается повторно,
    с бОльшим n и более поздним watermark, а не как отдельное событие где-то ещё."""

    def process(self, key, context, elements):
        rows = [json.loads(e) for e in elements]
        window = context.window()
        offsets = sorted(r["off"] for r in rows)
        log(
            f"WINDOW key={key} range=[{window.start},{window.end}) "
            f"watermark={context.current_watermark()} n={len(rows)} offsets={offsets}"
        )
        yield (key, window.start, window.end, len(rows))


class PrintLateData(ProcessFunction):
    """Side output: события, которые пришли позже window_end + allowedLateness."""

    def process_element(self, value, ctx):
        row = json.loads(value)
        log(
            f"SIDE OUTPUT (слишком поздно) key={row['sensor']} off={row['off']} "
            f"watermark={ctx.timer_service().current_watermark()}"
        )
        yield value


def build_job(group_id: str):
    env = StreamExecutionEnvironment.get_execution_environment()
    env.add_jars(KAFKA_CONNECTOR_JAR)
    env.set_parallelism(1)

    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(BOOTSTRAP_SERVERS)
        .set_topics(TOPIC)
        .set_group_id(group_id)
        .set_starting_offsets(KafkaOffsetsInitializer.latest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )
    strategy = (
        WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_millis(OUT_OF_ORDERNESS_MS))
        .with_timestamp_assigner(ExtractEventTime())
        .with_idleness(Duration.of_seconds(3))
    )
    stream = env.from_source(source, strategy, "kafka-watermark-events")
    windowed = (
        stream.key_by(lambda v: json.loads(v)["sensor"])
        .window(TumblingEventTimeWindows.of(Time.seconds(WINDOW_SECONDS)))
        .allowed_lateness(ALLOWED_LATENESS_MS)
        .side_output_late_data(LATE_DATA_TAG)
        .process(PrintWindowResult())
    )
    windowed.get_side_output(LATE_DATA_TAG).process(PrintLateData())
    return env


def send(producer, sensor, offset_ms, base, tag=""):
    payload = json.dumps({"sensor": sensor, "ts": base + offset_ms, "off": offset_ms}).encode()
    producer.produce(TOPIC, key=sensor.encode(), value=payload)
    producer.flush(5)
    log(f"produced key={sensor} off={offset_ms} {tag}")


def scenario_late_but_allowed():
    """window0 у sensor-1 закрывается событием на ключе clock (не трогает elements
    sensor-1). Вскоре после закрытия шлём опоздавшее sensor-1 - ожидаем late firing."""
    log("=== сценарий 1: опоздание в пределах allowedLateness ===")
    from confluent_kafka import Producer

    def produce():
        time.sleep(2)
        producer = Producer({"bootstrap.servers": BOOTSTRAP_SERVERS})
        base = int(time.time() * 1000)
        send(producer, "sensor-1", 0, base)
        time.sleep(2)
        send(producer, "clock", 9000, base, tag="(двигает общий watermark)")
        time.sleep(6)
        # Дедлайн окна window0: end(5000) + allowedLateness(4000) = 9000 мс от начала.
        # Отправляем почти сразу после закрытия, пока watermark ещё далёк от дедлайна.
        send(producer, "sensor-1", 1000, base, tag="(опоздавшее, в пределах allowedLateness)")
        time.sleep(10)
        log("producer (сценарий 1) done")

    env = build_job("late_scenario_1")
    t = threading.Thread(target=produce, daemon=True)
    t.start()
    job_client = env.execute_async("watermark late firing demo")
    t.join()
    time.sleep(3)
    job_client.cancel()
    log("сценарий 1 завершён")


def scenario_too_late():
    """Та же схема, но опоздавшее событие отправляется после долгой паузы - к этому
    моменту watermark гарантированно ушёл за window_end + allowedLateness."""
    log("=== сценарий 2: опоздание за allowedLateness (side output) ===")
    from confluent_kafka import Producer

    def produce():
        time.sleep(2)
        producer = Producer({"bootstrap.servers": BOOTSTRAP_SERVERS})
        base = int(time.time() * 1000)
        send(producer, "sensor-1", 0, base)
        time.sleep(2)
        send(producer, "clock", 9000, base, tag="(двигает общий watermark)")
        time.sleep(10)
        log("--- долгая пауза, чтобы дедлайн window0 остался далеко позади ---")
        time.sleep(15)
        send(producer, "sensor-1", 1000, base, tag="(слишком поздно -> side output)")
        time.sleep(10)
        log("producer (сценарий 2) done")

    env = build_job("late_scenario_2")
    t = threading.Thread(target=produce, daemon=True)
    t.start()
    job_client = env.execute_async("watermark side output demo")
    t.join()
    time.sleep(3)
    job_client.cancel()
    log("сценарий 2 завершён")


if __name__ == "__main__":
    scenario_late_but_allowed()
    time.sleep(3)
    scenario_too_late()
