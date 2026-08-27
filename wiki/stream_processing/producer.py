# confluent-kafka 2.15.0, Kafka 4.3.0 (образ apache/kafka, стенд event_streaming),
# прогнано на стенде 2026-08-27
"""
Продюсер для демо потоковой обработки: шлёт события температурных датчиков
намеренно не по порядку event time, включая пару "опоздавших" событий,
чтобы процессор (processor.py) мог показать механизм watermark и tumbling-окна.

Топик stream_processing_events создаётся заранее (autocreate выключен на стенде):
    docker exec event_streaming_kafka /opt/kafka/bin/kafka-topics.sh \
        --create --topic stream_processing_events \
        --bootstrap-server localhost:9092 --partitions 1 --replication-factor 1
"""
import json
import sys
import time

from confluent_kafka import Producer

TOPIC = "stream_processing_events"
BOOTSTRAP = "localhost:9092"

# (sensor_id, event_time_sec, value). event_time — условная шкала в секундах от
# начала демо, а не время настенных часов: так прогон воспроизводим независимо
# от того, когда его реально запустили. Порядок в списке — порядок ОТПРАВКИ,
# то есть порядок прихода в топик, и он умышленно не совпадает с порядком
# event_time (сеть и разные датчики доставляют события вразнобой).
EVENTS = [
    ("s1", 2, 20.0),
    ("s1", 5, 21.0),
    ("s2", 1, 15.0),
    ("s1", 12, 22.0),
    ("s2", 8, 16.0),
    ("s1", 9, 23.0),
    ("s3", 15, 30.0),
    ("s1", 3, 19.5),   # опоздавшее: придёт после того, как окно [0,10) уже закроется по watermark
    ("s2", 18, 17.0),
    ("s1", 22, 24.0),
    ("s3", 25, 31.0),
    ("s2", 13, 16.5),  # опоздавшее: окно [10,20) к этому моменту уже закрыто
    ("s1", 45, 26.0),  # резкий скачок вперёд продвигает watermark и закрывает окно [20,30)
    ("s2", 41, 18.0),
]


def delivery_report(err, msg):
    if err is not None:
        print(f"ошибка доставки: {err}", file=sys.stderr)


def main():
    producer = Producer({"bootstrap.servers": BOOTSTRAP})
    t0 = time.time()
    for sensor_id, event_time, value in EVENTS:
        payload = json.dumps({
            "sensor_id": sensor_id,
            "event_time": event_time,
            "value": value,
        }).encode("utf-8")
        producer.produce(TOPIC, key=sensor_id.encode("utf-8"), value=payload,
                          callback=delivery_report)
        producer.poll(0)
    producer.flush(10)
    elapsed = time.time() - t0
    print(f"отправлено {len(EVENTS)} событий в '{TOPIC}' за {elapsed:.3f} с")


if __name__ == "__main__":
    main()
