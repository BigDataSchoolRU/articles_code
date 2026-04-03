import polars as pl

# Eager mode (Жадный режим - аналог Pandas)
# Читает весь файл в память сразу
df = pl.read_csv("data.csv")

# Фильтрация и создание новой колонки
# Синтаксис выражений pl.col()
res = df.filter(
    pl.col("category") == "Technology"
).with_columns(
    (pl.col("price") * 0.8).alias("discounted_price")
)

print(res.head())
