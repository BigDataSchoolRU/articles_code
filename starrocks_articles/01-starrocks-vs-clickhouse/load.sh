#!/usr/bin/env bash
# Код к статье "StarRocks против ClickHouse: сравнение архитектур для аналитики"
# из серии материалов по StarRocks, "Школа Больших Данных".
# Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-vs-clickhouse-analytics-architecture/
# Автор: Bigdataschool.ru   "Школа Больших Данных"
# Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
#
# протестировано для StarRocks 3.5.0 и ClickHouse 26.3 LTS
# Загрузка сгенерированных CSV в оба движка.
set -e

# StarRocks Stream Load через HTTP на FE (порт 8030)
for t in customers products orders order_items; do
  case $t in
    customers)   COLS="customer_id,name,region_id,signup_date" ;;
    products)    COLS="product_id,name,category_id,price" ;;
    orders)      COLS="order_id,customer_id,order_date,status" ;;
    order_items) COLS="item_id,order_id,product_id,quantity" ;;
  esac
  curl --location-trusted -u root: \
    -H "column_separator:," \
    -H "columns:${COLS}" \
    -T "dataset/${t}.csv" \
    "http://127.0.0.1:8030/api/shop/${t}/_stream_load"
done

# ClickHouse вставка из файлов
for t in customers products orders order_items; do
  clickhouse-client --host 127.0.0.1 --port 9000 \
    --query "INSERT INTO shop.${t} FORMAT CSV" < "dataset/${t}.csv"
done

echo "load complete"
