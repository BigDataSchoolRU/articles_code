# confluent-kafka 2.15.0, duckdb 1.5.5, прогнано на стенде 2026-09-05
"""Speed layer: инкрементальная дельта поверх watermark batch_view. Каждый прогон перечитывает
лог Kafka с начала своей новой группой и сам решает по watermark, что уже учтено batch'ем —
а не полагается на сохранённые оффсеты консьюмер-группы. После следующего прогона batch layer
эта дельта устаревает и должна быть пересчитана заново с новым watermark."""
import json
import time
import uuid
from collections import defaultdict
from pathlib import Path

import duckdb
from confluent_kafka import Consumer, KafkaError

BROKER = "localhost:9092"
TOPIC = "lambda_architecture_events"
DB_FILE = Path(__file__).parent / "lambda_view.duckdb"
POLL_TIMEOUT = 1.0
IDLE_LIMIT = 5  # столько пустых опросов подряд после назначения партиций считаем концом лога


def read_watermark(con) -> int:
    row = con.execute("SELECT watermark FROM batch_meta").fetchone()
    if row is None:
        raise SystemExit("нет batch_meta, сначала запустите batch_layer.py")
    return row[0]


def consume_since(watermark: int) -> tuple[dict, int, int, float]:
    consumer = Consumer({
        "bootstrap.servers": BROKER,
        "group.id": f"speed_layer_{uuid.uuid4().hex[:8]}",  # своя группа на каждый прогон
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([TOPIC])

    delta: dict = defaultdict(int)
    seen_total, seen_new, idle = 0, 0, 0
    t0 = time.time()
    while idle < IDLE_LIMIT:
        msg = consumer.poll(POLL_TIMEOUT)
        if msg is None:
            idle += 1
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                print(f"ОШИБКА: {msg.error()}")
            continue
        idle = 0
        event = json.loads(msg.value())
        seen_total += 1
        if event["ts"] > watermark:
            delta[event["page"]] += event["views"]
            seen_new += 1
    elapsed = time.time() - t0
    consumer.close()
    return delta, seen_total, seen_new, elapsed


def main() -> None:
    con = duckdb.connect(str(DB_FILE))
    watermark = read_watermark(con)
    delta, seen_total, seen_new, elapsed = consume_since(watermark)

    print(f"прочитано из Kafka событий: {seen_total}, новее watermark {watermark}: {seen_new}, за {elapsed:.2f} с")

    con.execute("CREATE OR REPLACE TABLE speed_view (page VARCHAR, views BIGINT)")
    for page, views in delta.items():
        con.execute("INSERT INTO speed_view VALUES (?, ?)", [page, views])

    print("speed_view (дельта поверх batch_view):")
    if not delta:
        print("  пусто: новых событий после последнего batch-прогона нет")
    for page, views in sorted(delta.items()):
        print(f"  {page}: +{views} просмотров")
    con.close()


if __name__ == "__main__":
    main()
