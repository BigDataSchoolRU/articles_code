# Great Expectations (GX Core) 1.11.1, PostgreSQL 18.4, прогнано на стенде 2026-08-30
"""
Проверяет таблицу orders из data_quality_demo (см. db_setup.py) через GX Core:
Data Context -> Data Source/Asset -> Batch Definition -> Expectation Suite ->
Validation Definition -> Checkpoint -> результат и Data Docs.

Каждый Expectation в suite закрывает одну дименсию качества данных — комментарий
у каждого называет её явно, чтобы связь "дименсия -> проверка в коде" была видна
напрямую, а не только в тексте статьи.
"""

import shutil
import time
from datetime import date

import great_expectations as gx
from great_expectations.checkpoint.actions import UpdateDataDocsAction
from great_expectations.expectations import (
    ExpectColumnValuesToBeBetween,
    ExpectColumnValuesToBeUnique,
    ExpectColumnValuesToBeInSet,
    ExpectColumnValuesToMatchRegex,
    ExpectColumnValuesToNotBeNull,
)

CONNECTION_STRING = "postgresql+psycopg2://techfriends@localhost:5432/data_quality_demo"
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# file-режим Data Context, а не ephemeral: только он пишет отчёт Data Docs на диск
shutil.rmtree("gx", ignore_errors=True)
context = gx.get_context(mode="file", project_root_dir=".")

data_source = context.data_sources.add_postgres(
    "orders_postgres", connection_string=CONNECTION_STRING
)
data_asset = data_source.add_table_asset(
    "orders_asset", table_name="orders", schema_name="public"
)
batch_definition = data_asset.add_batch_definition_whole_table("orders_batch")

suite = gx.ExpectationSuite(name="orders_quality_suite")

# полнота (completeness): обязательные поля не должны быть пустыми
suite.add_expectation(ExpectColumnValuesToNotBeNull(column="customer_email"))
suite.add_expectation(ExpectColumnValuesToNotBeNull(column="amount"))

# уникальность (uniqueness): order_id — первичный ключ заказа
suite.add_expectation(ExpectColumnValuesToBeUnique(column="order_id"))

# валидность (validity): формат email и допустимый диапазон суммы
suite.add_expectation(
    ExpectColumnValuesToMatchRegex(column="customer_email", regex=EMAIL_REGEX, mostly=1.0)
)
suite.add_expectation(
    ExpectColumnValuesToBeBetween(column="amount", min_value=0, max_value=5000, mostly=1.0)
)

# согласованность (consistency): статус только в каноническом написании,
# а не "PAID"/"Paid"/"paid" одновременно
suite.add_expectation(
    ExpectColumnValuesToBeInSet(
        column="status", value_set=["paid", "pending", "cancelled"], mostly=1.0
    )
)

# своевременность (timeliness): дата заказа не может быть в будущем относительно прогона
suite.add_expectation(
    ExpectColumnValuesToBeBetween(
        column="order_date", min_value="2000-01-01", max_value=date.today().isoformat()
    )
)

suite = context.suites.add(suite)

validation_definition = context.validation_definitions.add(
    gx.ValidationDefinition(name="orders_validation", data=batch_definition, suite=suite)
)

checkpoint = context.checkpoints.add(
    gx.Checkpoint(
        name="orders_checkpoint",
        validation_definitions=[validation_definition],
        actions=[UpdateDataDocsAction(name="update_data_docs")],
    )
)

t0 = time.time()
result = checkpoint.run()
elapsed = time.time() - t0

print(f"Checkpoint выполнен за {elapsed:.2f} с, общий success={result.success}")
print()

for validation_result in result.run_results.values():
    for expectation_result in validation_result.results:
        config = expectation_result["expectation_config"]
        column = config["kwargs"].get("column")
        status = "OK" if expectation_result["success"] else "FAIL"
        unexpected = expectation_result["result"].get("unexpected_count", "-")
        print(f"[{status}] {config['type']:<32} column={column:<16} unexpected={unexpected}")

print()
docs_urls = context.get_docs_sites_urls()
print(f"Data Docs: {docs_urls[0]['site_url']}")
