# прогон на confluent-kafka 2.15.0, Apache Kafka 4.3.0, Schema Registry 8.3.1
from confluent_kafka import Producer, Consumer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroSerializer, AvroDeserializer
from confluent_kafka.serialization import SerializationContext, MessageField

TOPIC = "orders"
SCHEMA = """
{"type":"record","name":"Order","fields":[
 {"name":"id","type":"string"},
 {"name":"amount","type":"double"},
 {"name":"currency","type":"string","default":"RUB"}]}
"""

# клиент реестра: через него сериализатор регистрирует схему и получает её идентификатор
sr = SchemaRegistryClient({"url": "http://localhost:8081"})
serializer = AvroSerializer(sr, SCHEMA)
ctx = SerializationContext(TOPIC, MessageField.VALUE)

# сериализация превращает словарь в байты: 5 байт префикса плюс тело Avro
payload = serializer({"id": "A-1001", "amount": 149.5, "currency": "RUB"}, ctx)
print("байт всего:", len(payload))
print("префикс:", payload[:5].hex(" "))
print("магический байт:", payload[0], "| schema id:", int.from_bytes(payload[1:5], "big"))

producer = Producer({"bootstrap.servers": "localhost:9092"})
producer.produce(TOPIC, value=payload)
producer.flush()

# потребитель читает сырые байты, десериализатор сам ходит в реестр за схемой по id
consumer = Consumer({"bootstrap.servers": "localhost:9092",
                     "group.id": "wiki_demo", "auto.offset.reset": "earliest"})
consumer.subscribe([TOPIC])
message = consumer.poll(15)
deserializer = AvroDeserializer(sr, SCHEMA)
print("прочитано:", deserializer(message.value(), ctx))
consumer.close()
