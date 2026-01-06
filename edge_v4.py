import time
import random
import json
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion # Импорт для совместимости с v2

# Конфигурация
BROKER = "localhost" # Публичный тестовый брокер
TOPIC = "factory/sensor/temp_alert"
CRITICAL_TEMP = 75.0

# Функция имитации датчика (генерация данных)
def read_sensor_data():
    # Имитируем температуру от 60 до 90 градусов
    return round(random.uniform(60.0, 90.0), 2)

def run_edge_device():
    # Указываем версию API явно, чтобы избежать ошибки в новых версиях библиотеки
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="EdgeNode_01")
    
    try:
        print(f"Connecting to broker {BROKER}...")
        client.connect(BROKER, 1883, 60)
        client.loop_start() # Запускаем фоновый поток для сети
        time.sleep(1) # Небольшая пауза для установки соединения
        
        while True:
            # 1. Сбор данных (Ingestion)
            current_temp = read_sensor_data()
            
            # 2. Локальная обработка (Edge Processing)
            # Логика: отправляем только если температура > CRITICAL_TEMP
            if current_temp > CRITICAL_TEMP:
                payload = json.dumps({
                    "sensor_id": "temp_01",
                    "value": current_temp,
                    "alert": "OVERHEAT",
                    "timestamp": time.time()
                })
                
                # 3. Отправка данных (Transmission)
                client.publish(TOPIC, payload)
                print(f"[ALARM] High temp detected: {current_temp}°C -> Sent to Cloud")
            else:
                # Данные отбрасываются (Filtering), экономим трафик
                print(f"[OK] Temp normal: {current_temp}°C -> Ignored")
                
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping Edge Node...")
        client.loop_stop()

if __name__ == "__main__":
    run_edge_device()
