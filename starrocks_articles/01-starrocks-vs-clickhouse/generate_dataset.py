# Код к статье "StarRocks против ClickHouse: сравнение архитектур для аналитики"
# из серии материалов по StarRocks, "Школа Больших Данных".
# Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-vs-clickhouse-analytics-architecture/
# Автор: Bigdataschool.ru   "Школа Больших Данных"
# Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
#
# протестировано для Python 3.12
# Генератор нормализованного датасета интернет-магазина: customers, products, orders, order_items.
#
# Объём задаётся параметром --scale (множитель базового набора).
#   scale 1  -> примерно 4.4 ГБ   (100 млн позиций)  быстрый прогон
#   scale 3  -> примерно 13 ГБ    (300 млн позиций)
#   scale 4  -> примерно 18 ГБ    (400 млн позиций)  полноценный нагрузочный тест
# Для мгновенной проверки схемы возьмите --scale 0.01 (примерно 45 МБ).
#
# Запуск:
#   python3 generate_dataset.py --scale 1 --out dataset
#
import csv
import random
import os
import argparse
from datetime import date, timedelta

BASE_CUSTOMERS = 5_000_000
BASE_PRODUCTS = 500_000
BASE_ORDERS = 40_000_000
BASE_ITEMS = 100_000_000

SIGNUP_START = date(2023, 1, 1)
ORDER_START = date(2024, 1, 1)
STATUSES = ["paid", "shipped", "cancelled"]


def log(msg):
    print(msg, flush=True)


def gen_customers(path, n):
    log(f"customers: {n:,} строк ...")
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")  # важно: \n, иначе StarRocks оставит \r в последней колонке
        for cid in range(1, n + 1):
            signup = SIGNUP_START + timedelta(days=random.randint(0, 900))
            w.writerow([cid, f"customer_{cid}", random.randint(1, 90), signup])


def gen_products(path, n):
    log(f"products: {n:,} строк ...")
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")  # важно: \n, иначе StarRocks оставит \r в последней колонке
        for pid in range(1, n + 1):
            price = round(random.uniform(1, 5000), 2)
            w.writerow([pid, f"product_{pid}", random.randint(1, 200), price])


def gen_orders(path, n, n_customers):
    log(f"orders: {n:,} строк ...")
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")  # важно: \n, иначе StarRocks оставит \r в последней колонке
        for oid in range(1, n + 1):
            odate = ORDER_START + timedelta(days=random.randint(0, 550))
            w.writerow([oid, random.randint(1, n_customers), odate, random.choice(STATUSES)])
            if oid % 5_000_000 == 0:
                log(f"  orders {oid:,}")


def gen_items(path, n, n_orders, n_products):
    log(f"order_items: {n:,} строк ...")
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")  # важно: \n, иначе StarRocks оставит \r в последней колонке
        for iid in range(1, n + 1):
            w.writerow([iid, random.randint(1, n_orders), random.randint(1, n_products), random.randint(1, 10)])
            if iid % 10_000_000 == 0:
                log(f"  order_items {iid:,}")


def main():
    ap = argparse.ArgumentParser(description="Генератор датасета для стенда StarRocks vs ClickHouse")
    ap.add_argument("--scale", type=float, default=1.0, help="множитель объёма, 1.0 это примерно 4.4 ГБ")
    ap.add_argument("--out", default="dataset", help="каталог для CSV")
    ap.add_argument("--seed", type=int, default=42, help="seed для воспроизводимости")
    args = ap.parse_args()

    random.seed(args.seed)
    os.makedirs(args.out, exist_ok=True)

    n_customers = max(1, int(BASE_CUSTOMERS * args.scale))
    n_products = max(1, int(BASE_PRODUCTS * args.scale))
    n_orders = max(1, int(BASE_ORDERS * args.scale))
    n_items = max(1, int(BASE_ITEMS * args.scale))

    log(f"scale={args.scale}, каталог={args.out}")
    gen_customers(os.path.join(args.out, "customers.csv"), n_customers)
    gen_products(os.path.join(args.out, "products.csv"), n_products)
    gen_orders(os.path.join(args.out, "orders.csv"), n_orders, n_customers)
    gen_items(os.path.join(args.out, "order_items.csv"), n_items, n_orders, n_products)

    total = sum(os.path.getsize(os.path.join(args.out, f)) for f in os.listdir(args.out))
    log(f"готово. Суммарный объём: {total / 1e9:.2f} ГБ")


if __name__ == "__main__":
    main()
