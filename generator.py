# код Producer для статьи https://bigdataschool.ru/wiki/dataflow-wiki/
import time
import json
import random
from kafka import KafkaProducer

# Подключение к локальному Docker-контейнеру
producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

TOPIC_NAME = 'sensor-data'

print(f"🚀 Запуск потока данных в топик '{TOPIC_NAME}'...")

try:
    while True:
        # Эмуляция данных
        data = {
            "sensor_id": "turbine-local-01",
            "timestamp": time.time(),
            "vibration_level": round(random.uniform(0.5, 12.0), 2),
            "status": "active"
        }

        producer.send(TOPIC_NAME, value=data)
        producer.flush() # Принудительная отправка из буфера

        print(f"Sent: {data}")
        time.sleep(1)
except KeyboardInterrupt:
    producer.close()
