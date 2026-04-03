import csv
import random

header = ['id', 'category', 'price', 'sales']
categories = ['Technology', 'Clothing', 'Food', 'Books']

with open('data.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(header)
    for i in range(1, 1001):
        cat = random.choice(categories)
        price = round(random.uniform(10.0, 500.0), 2)
        sales = random.randint(1, 100)
        writer.writerow([i, cat, price, sales])
