# fastavro 1.12.2, локально без Docker и реестра схем, прогнано на стенде 2026-09-05
#
# Механизм Avro schema resolution: писатель и читатель используют РАЗНЫЕ схемы одной и
# той же записи, и fastavro сопоставляет их поле за полем по имени, а не по позиции.
# Три сценария: совместимое добавление поля, удаление поля, переименование без alias.

import io

import fastavro
from fastavro.read import SchemaResolutionError

# writer schema v1: заказ с идентификатором, суммой и статусом
writer_schema_v1 = {
    "type": "record",
    "name": "Order",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "amount", "type": "double"},
        {"name": "status", "type": "string"},
    ],
}

# reader schema v2: добавлено поле currency с default, удалено поле status
reader_schema_v2 = {
    "type": "record",
    "name": "Order",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "amount", "type": "double"},
        {"name": "currency", "type": "string", "default": "RUB"},
    ],
}

# reader schema v3: то же самое поле currency, но переименовано в curr без alias —
# для резолюции это не переименование, а новое неизвестное поле читателя
reader_schema_v3_renamed_no_alias = {
    "type": "record",
    "name": "Order",
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "amount", "type": "double"},
        {"name": "curr", "type": "string", "default": "RUB"},
    ],
}


def write_with_schema(record: dict, schema: dict) -> bytes:
    """Пишет одну запись в бинарный Avro писателем указанной схемы."""
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, record)
    return buf.getvalue()


def read_with_schema(data: bytes, writer_schema: dict, reader_schema: dict) -> dict:
    """Читает байты, записанные writer_schema, через reader_schema — это и есть
    schema resolution: fastavro сопоставляет поля по имени между двумя схемами."""
    buf = io.BytesIO(data)
    return fastavro.schemaless_reader(buf, writer_schema, reader_schema)


def scenario_field_added_with_default():
    print("--- Сценарий 1: writer v1 -> reader v2, поле currency добавлено с default ---")
    record = {"id": "A-1001", "amount": 149.5, "status": "paid"}
    data = write_with_schema(record, writer_schema_v1)
    print(f"записано writer v1: {record}")
    print(f"байт на диске: {len(data)}")
    result = read_with_schema(data, writer_schema_v1, reader_schema_v2)
    print(f"прочитано reader v2: {result}")
    print("поле status отсутствует в reader v2 и молча отброшено")
    print("поле currency отсутствует у writer и заполнено default-значением")


def scenario_removed_field_breaks_old_reader():
    print()
    print("--- Сценарий 2: writer v2 (без status) -> reader v1 (status обязателен, без default) ---")
    record = {"id": "A-1002", "amount": 89.0, "currency": "USD"}
    data = write_with_schema(record, reader_schema_v2)
    print(f"записано writer v2: {record}")
    try:
        result = read_with_schema(data, reader_schema_v2, writer_schema_v1)
        print(f"прочитано reader v1: {result}")
    except SchemaResolutionError as exc:
        print(f"резолюция отказала: {exc}")
        print("это forward-совместимость (старый читатель против новых данных), а не")
        print("backward: поле status удалено в v2 без default в v1, и читателю, который")
        print("ещё не обновился на v2, взять значение status неоткуда")


def scenario_rename_without_alias_fails():
    print()
    print("--- Сценарий 3: переименование currency -> curr БЕЗ alias ---")
    record = {"id": "A-1003", "amount": 12.3, "currency": "EUR"}
    data = write_with_schema(record, reader_schema_v2)
    print(f"записано writer v2: {record}")
    try:
        result = read_with_schema(data, reader_schema_v2, reader_schema_v3_renamed_no_alias)
        print(f"прочитано reader v3: {result}")
        print("резолюция НЕ считает curr тем же полем, что currency: поле writer'а с")
        print("именем currency проигнорировано как незнакомое читателю, curr в результате")
        print("получил собственное default-значение, а не значение из данных")
        assert result["curr"] == "RUB", "curr должен взять default, а не значение currency"
        assert "currency" not in result, "currency не должно попасть в результат reader v3"
    except SchemaResolutionError as exc:
        print(f"резолюция отказала: {exc}")


if __name__ == "__main__":
    scenario_field_added_with_default()
    scenario_removed_field_breaks_old_reader()
    scenario_rename_without_alias_fails()
