import pyarrow as pa
import pandas as pd
import numpy as np

# 1. Создание данных
data = {
    'product_id': np.arange(1, 6),
    'price': np.array([10.5, 20.0, 15.75, 5.0, 100.0]),
    'category': ['food', 'electronics', 'food', 'home', 'electronics']
}

# 2. Конвертация Pandas -> Arrow Table
# Это происходит очень быстро
df = pd.DataFrame(data)
arrow_table = pa.Table.from_pandas(df)

print(f"Тип объекта: {type(arrow_table)}")
print(arrow_table.schema)

# 3. Обратная конвертация Arrow -> Pandas
# Благодаря Zero-Copy (где возможно) это мгновенно
df_new = arrow_table.to_pandas()

# 4. Сохранение на диск (формат Feather/IPC использует память Arrow "как есть")
import pyarrow.feather as feather
feather.write_feather(df, 'data.arrow')
