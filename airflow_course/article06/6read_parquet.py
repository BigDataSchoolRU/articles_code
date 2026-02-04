import pandas as pd

# Читаем файл
df = pd.read_parquet("final_report.parquet")

# Показываем красивую таблицу
print(df)
