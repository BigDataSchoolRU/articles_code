# pyfluss 1.0.0, Apache Fluss 1.0.0 local cluster, прогнано на стенде 2026-11-14
"""Таблица с первичным ключом в Apache Fluss: upsert, частичное обновление, удаление,
точечный lookup по ключу и changelog, который та же таблица отдаёт потоковому читателю.

Запуск: python pk_table_demo.py [--bootstrap localhost:9123]
"""
import argparse
import asyncio
import time

import fluss
import pyarrow as pa

DB = "shop"
TABLE = "orders"


async def connect(bootstrap: str) -> fluss.FlussConnection:
    """Подключение к кластеру и ожидание, пока зарегистрируется TabletServer."""
    deadline = time.monotonic() + 90
    while True:
        try:
            conn = await fluss.FlussConnection.create(fluss.Config({"bootstrap.servers": bootstrap}))
            nodes = await conn.get_admin().get_server_nodes()
            kinds = sorted(n.server_type for n in nodes)
            if any("Tablet" in k for k in kinds):
                print("кластер:", ", ".join(f"{n.server_type} {n.host}:{n.port}" for n in nodes))
                return conn
            await conn.close()
        except Exception as e:  # кластер ещё поднимается
            last = e
        if time.monotonic() > deadline:
            raise RuntimeError(f"кластер не готов за 90 с: {last!r}")
        await asyncio.sleep(1)


def show(row) -> str:
    if row is None:
        return "None (ключа нет)"
    return f"{row['order_id']} {row['customer']:<6} {row['status']:<9} {row['amount']:>7.2f}"


async def main(bootstrap: str) -> None:
    conn = await connect(bootstrap)
    admin = conn.get_admin()
    path = fluss.TablePath(DB, TABLE)

    # 1. Схема задаётся через Arrow, первичный ключ отдельным списком. Наличие ключа делает
    # таблицу Primary Key Table: под ней KV-хранилище на RocksDB плюс changelog.
    schema = fluss.Schema(
        pa.schema([
            ("order_id", "int64"),
            ("customer", "string"),
            ("status", "string"),
            ("amount", "float64"),
        ]),
        primary_keys=["order_id"],
    )
    await admin.create_database(DB, ignore_if_exists=True)
    await admin.drop_table(path, ignore_if_not_exists=True)
    await admin.create_table(path, fluss.TableDescriptor(schema, bucket_count=1))
    table = await conn.get_table(path)
    info = await admin.get_table_info(path)
    print(f"таблица {path.table_path_str()}: первичный ключ {info.get_primary_keys()}, "
          f"бакетов {info.num_buckets}, has_primary_key={table.has_primary_key()}")
    props = info.get_properties()
    for k in sorted(props):
        print(f"  {k} = {props[k]}")

    writer = table.new_upsert().create_writer()
    lookuper = table.new_lookup().create_lookuper()

    # 2. Три новых заказа: для ключей, которых ещё нет, upsert работает как вставка
    print("\n--- шаг 1: три вставки")
    for row in [
        {"order_id": 1, "customer": "anna", "status": "created", "amount": 120.0},
        {"order_id": 2, "customer": "boris", "status": "created", "amount": 75.5},
        {"order_id": 3, "customer": "vera", "status": "created", "amount": 310.0},
    ]:
        writer.upsert(row)
    await writer.flush()
    print("lookup 2:", show(await lookuper.lookup({"order_id": 2})))

    # 3. Тот же ключ ещё раз: строка заменяется целиком, отдельного UPDATE нет
    print("\n--- шаг 2: upsert по существующему ключу 2 (status -> paid)")
    await writer.upsert({"order_id": 2, "customer": "boris", "status": "paid", "amount": 75.5}).wait()
    print("lookup 2:", show(await lookuper.lookup({"order_id": 2})))

    # 4. Повтор той же самой строки: проверяем, пишет ли Fluss событие, если ничего не поменялось
    print("\n--- шаг 3: повторный upsert той же строки для ключа 2")
    await writer.upsert({"order_id": 2, "customer": "boris", "status": "paid", "amount": 75.5}).wait()

    # 5. Частичное обновление: передаём ключ и только те колонки, которые меняем
    print("\n--- шаг 4: partial update ключа 3, только amount")
    partial = table.new_upsert().partial_update_by_name(["order_id", "amount"]).create_writer()
    await partial.upsert({"order_id": 3, "amount": 290.0}).wait()
    print("lookup 3:", show(await lookuper.lookup({"order_id": 3})))

    # 6. Удаление по ключу
    print("\n--- шаг 5: delete ключа 1")
    await writer.delete({"order_id": 1}).wait()
    for k in (1, 2, 3):
        print(f"lookup {k}:", show(await lookuper.lookup({"order_id": k})))

    # 7. Задержка lookup. Клиент копит запросы в батч до 128 ключей и ждёт заполнения до 100 мс
    # (lookup_batch_timeout_ms в Rust-клиенте). Один Lookuper в pyfluss обслуживает запросы по
    # одному, поэтому последовательные lookup каждый раз упираются в этот таймаут.
    n = 50
    t0 = time.perf_counter()
    for i in range(n):
        await lookuper.lookup({"order_id": 2 + i % 2})
    print(f"\n{n} последовательных lookup через один Lookuper: {(time.perf_counter() - t0) / n * 1000:.1f} мс на запрос")
    # Много Lookuper параллельно наполняют общий батч, и он уходит на сервер без ожидания
    for k in (1, 32, 128):
        lks = [table.new_lookup().create_lookuper() for _ in range(k)]
        t0 = time.perf_counter()
        found = await asyncio.gather(*[lks[i % k].lookup({"order_id": 2 + i % 2}) for i in range(512)])
        print(f"512 lookup параллельно через {k:>3} Lookuper: {(time.perf_counter() - t0) * 1000:7.0f} мс всего, "
              f"найдено {sum(r is not None for r in found)}")

    # 8. Changelog: та же таблица читается как поток изменений с начального офсета.
    # Именно его потребляет Flink-джоба, подписанная на PK-таблицу.
    end = (await admin.list_offsets(path, [0], fluss.OffsetSpec.latest()))[0]
    print(f"\n--- changelog таблицы {TABLE}, бакет 0, офсеты 0..{end - 1}")
    scanner = await table.new_scan().create_log_scanner()
    scanner.subscribe(0, fluss.EARLIEST_OFFSET)
    seen = 0
    idle = 0
    while seen < end and idle < 10:
        records = await scanner.poll(1000)
        if records.is_empty():
            idle += 1
            continue
        for rec in records:
            r = rec.row
            print(f"offset {rec.offset:>2}  {rec.change_type.short_string()}  {show(r)}")
            seen += 1
    print(f"событий в changelog: {seen}")

    await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", default="localhost:9123")
    asyncio.run(main(ap.parse_args().bootstrap))
