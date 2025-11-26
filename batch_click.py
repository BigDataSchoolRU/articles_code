import random
import time
from datetime import datetime, timedelta

from clickhouse_driver import Client


# Функция генерации одной пачки данных
def generate_batch(size):
    now = datetime.now()
    week_ago = now - timedelta(days=7)

    urls = [
        "https://bigdataschool.ru/",
        "https://bigdataschool.ru/wiki/",
        "https://bigdataschool.ru/about/",
        "https://bigdataschool.ru/contact/",
        "https://bigdataschool.ru/blog/",
    ]
    browsers = ["Chrome", "Firefox", "Safari", "Edge", "Opera", "Yandex"]
    regions = ["Moscow", "SPB", "Siberia", "Ural", "FarEast", "Central"]

    batch = []
    for _ in range(size):
        # случайная дата за последнюю неделю
        delta_seconds = random.randint(0, int((now - week_ago).total_seconds()))
        ts = week_ago + timedelta(seconds=delta_seconds)

        event_type = random.choice(["view", "click"])

        row = {
            "timestamp": ts,
            "user_id": random.randint(1, 1_000_000),
            "url": random.choice(urls),
            "event_type": event_type,
            "browser": random.choice(browsers),
            "region": random.choice(regions),
        }
        batch.append(row)

    return batch


def main():
    # Подключение к ClickHouse
    try:
        client = Client(
            host="localhost",
            port=9000,
            user="default",
            password="",
            database="default",
        )
        print("Подключение к ClickHouse установлено.")
    except Exception as e:
        print(f"Ошибка при подключении к ClickHouse: {e}")
        return

    batch_size = 5000

    try:
        while True:
            batch = generate_batch(batch_size)

            try:
                client.execute(
                    """
                    INSERT INTO web_analytics 
                        (timestamp, user_id, url, event_type, browser, region)
                    VALUES
                    """,
                    batch,
                )
                print(f"Вставлено строк: {len(batch)}")
            except Exception as e:
                print(f"Ошибка при вставке данных: {e}")

            time.sleep(1)

    except KeyboardInterrupt:
        print("Остановка по Ctrl+C.")
    finally:
        # Явное закрытие соединения (на всякий случай)
        try:
            client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
