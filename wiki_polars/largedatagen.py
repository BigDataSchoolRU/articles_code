import csv
import random

# Определяем структуру будущего датасета
header = ['id', 'region', 'product_id', 'sales', 'date']
regions = ['North', 'South', 'East', 'West', 'Central']

print("Начинаем генерацию large_data.csv...")

# Открываем файл для записи
with open('large_data.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(header)
    
    # Генерируем 100 000 строк для имитации объема
    for i in range(1, 100001):
        region = random.choice(regions)
        product_id = random.randint(100, 500)
        # Генерируем продажи, чтобы часть была больше 100
        sales = random.randint(10, 500) 
        date = f"2023-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"
        
        writer.writerow([i, region, product_id, sales, date])

print("Файл успешно создан! Можно запускать ленивый план.")
