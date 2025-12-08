#----код Consumer для Kafka для статьи https://bigdataschool.ru/wiki/dataflow-wiki/
import json
from kafka import KafkaConsumer

CRITICAL_THRESHOLD = 10.0

consumer = KafkaConsumer(
    'sensor-data',
    bootstrap_servers=['localhost:9092'],
    auto_offset_reset='earliest', # Читать только новые
    group_id='alert-system-group',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

print("🎧 Мониторинг запущен...")

for message in consumer:
    event = message.value
    vibration = event.get('vibration_level')
    if vibration > CRITICAL_THRESHOLD:
        print(f"  АЛЕРТ! Опасная вибрация: {vibration}")
    else:
        print(f"✅ Норма: {vibration}")
                                                                   
