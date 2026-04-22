import csv
import json
from confluent_kafka import Producer

# Укажи адреса своих нод
conf = {'bootstrap.servers': 'kafka-lab9-01.ru-central1.internal:9092,kafka-lab9-02.ru-central1.internal:9092,kafka-lab9-03.ru-central1.internal:9092'}
producer = Producer(conf)
topic_name = 'ecommerce_events'

def delivery_report(err, msg):
    if err is not None:
        print(f"Ошибка доставки: {err}")

# Берем один из твоих файлов
file_path = '2019-Oct.csv'

with open(file_path, mode='r', encoding='utf-8') as file:
    reader = csv.DictReader(file)
    count = 0
    
    for row in reader:
        # Пропускаем битые строки без user_id или цены
        if not row["user_id"] or not row["price"]:
            continue
            
        # Формируем словарь с нужными типами данных
        data = {
            "event_time": row["event_time"],
            "event_type": row["event_type"],
            "product_id": int(row["product_id"]),
            "price": float(row["price"]),
            "user_id": int(row["user_id"])
        }
        
        record = json.dumps(data)
        producer.produce(topic_name, record.encode('utf-8'), callback=delivery_report)
        
        count += 1
        # Сбрасываем буфер каждые 100 тысяч записей
        if count % 100000 == 0:
            producer.flush()
            print(f"Отправлено {count} записей...")

# Финальная очистка буфера
producer.flush()
print("Загрузка файла завершена успешно!")
