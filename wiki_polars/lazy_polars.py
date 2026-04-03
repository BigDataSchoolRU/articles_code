import polars as pl

# Создаем ленивый план (LazyFrame)
# Файл НЕ читается в этот момент
q = (
    pl.scan_csv("large_data.csv")
    .filter(pl.col("sales") > 100)
    .group_by("region")
    .agg([
        pl.col("sales").sum().alias("total_sales"),
        pl.col("sales").mean().alias("avg_sales"),
        pl.col("product_id").n_unique().alias("unique_products")
    ])
    .sort("total_sales", descending=True)
)

# Просмотр плана запроса (для отладки)
print(q.explain())

# Запуск вычислений
# Только здесь данные считываются и обрабатываются
result_df = q.collect()
print(result_df)
