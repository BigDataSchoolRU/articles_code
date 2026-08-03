# Код к статье "Потоковая загрузка из Apache Kafka в StarRocks через Routine Load"
# из серии материалов по StarRocks, "Школа Больших Данных".
# Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-routine-load-kafka/
# Автор: Bigdataschool.ru   "Школа Больших Данных"
# Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
#
# протестировано для Python 3.12 и kafka-python 2.0.2
# Непрерывный генератор JSON-событий заказов в топик Kafka.
# Формат события с вложенным объектом customer, чтобы показать маппинг
# вложенных полей через JSONPaths в StarRocks Routine Load.
#
# Установка зависимости (в venv, PEP 668):
#   python3 -m venv .venv && source .venv/bin/activate
#   pip install kafka-python
#
# Запуск:
#   python3 producer.py
import json
import random
import time
from datetime import datetime, date, timedelta
from kafka import KafkaProducer

# замените на адреса своих брокеров Kafka
BROKERS = ["kafka1:9092", "kafka2:9092", "kafka3:9092"]
TOPIC = "orders"
STATUSES = ["paid", "shipped", "cancelled"]
EVENTS_PER_SEC = 50  # темп генерации

producer = KafkaProducer(
    bootstrap_servers=BROKERS,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    acks="all",              # ждём подтверждения от лидера и реплик
    linger_ms=50,
    retries=5,
)


def make_event(order_id):
    odate = date(2026, 1, 1) + timedelta(days=random.randint(0, 200))
    return {
        "order_id": order_id,
        "customer": {
            "id": random.randint(1, 20_000_000),
            "region": random.randint(1, 90),
        },
        "order_date": odate.isoformat(),
        "status": random.choice(STATUSES),
        "amount": round(random.uniform(1, 5000), 2),
        "event_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    order_id = 1
    delay = 1.0 / EVENTS_PER_SEC
    print(f"пишем в топик {TOPIC} на {BROKERS}, {EVENTS_PER_SEC} событий в секунду")
    try:
        while True:
            event = make_event(order_id)
            producer.send(TOPIC, event)
            if order_id % 500 == 0:
                producer.flush()
                print(f"отправлено {order_id} событий")
            order_id += 1
            time.sleep(delay)
    except KeyboardInterrupt:
        producer.flush()
        print("остановлено, буфер сброшен")


if __name__ == "__main__":
    main()
