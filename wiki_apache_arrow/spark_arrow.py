import os

# 1. Задаем точный путь к Java
# (Тебе нужно будет вписать сюда свой путь из WSL)
os.environ["JAVA_HOME"] = "/usr/lib/jvm/java-17-openjdk-amd64"

# 2. Удаляем старый системный путь Spark для избежания конфликтов
if "SPARK_HOME" in os.environ:
    del os.environ["SPARK_HOME"]

from pyspark.sql import SparkSession
import numpy as np
import pandas as pd

spark = SparkSession.builder \
    .appName("ArrowExample") \
    .getOrCreate()

# Активация Arrow для оптимизации передачи данных
spark.conf.set("spark.sql.execution.arrow.pyspark.enabled", "true")

# Создаем большой DataFrame
data = pd.DataFrame({'a': np.random.randn(100000), 'b': np.random.randn(100000)})
sdf = spark.createDataFrame(data)

# Операция toPandas() теперь использует Arrow
# Без настройки выше это заняло бы гораздо больше времени на больших данных
pdf_result = sdf.select("a").toPandas()

# Пример Pandas UDF (Векторизованные вычисления)
from pyspark.sql.functions import pandas_udf

@pandas_udf("double")
def vector_plus_one(series: pd.Series) -> pd.Series:
    # Эта функция получает на вход не по одному числу, а сразу серию (batch)
    # благодаря Arrow, что работает в 10-100 раз быстрее обычных UDF
    return series + 1

sdf.withColumn("a_plus_1", vector_plus_one(sdf["a"])).show(5)
