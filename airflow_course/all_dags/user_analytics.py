import sys
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count

def main(input_path, output_path):
    # Создаем сессию
    spark = SparkSession.builder \
        .appName("AirflowUserAnalytics") \
        .getOrCreate()

    print(f"Reading from: {input_path}")
    
    # Читаем CSV. Так как хедер мы писали сами, указываем header=True
    df = spark.read.option("header", "true").csv(input_path)

    # Простая аналитика: сколько регистраций в каждую дату
    report = df.groupBy("date").agg(count("*").alias("total_users"))

    report.show()

    # Сохраняем результат (в формате Parquet, это стандарт для Big Data)
    report.write.mode("overwrite").parquet(output_path)
    
    spark.stop()

if __name__ == "__main__":
    # Аргументы передаются из Airflow
    if len(sys.argv) != 3:
        print("Usage: user_analytics.py <input_path> <output_path>")
        sys.exit(-1)
        
    main(sys.argv[1], sys.argv[2])

