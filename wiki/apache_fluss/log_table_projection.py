# pyfluss 1.0.0, Apache Fluss 1.0.0 local cluster, прогнано на стенде 2026-11-14
"""Лог-таблица Apache Fluss в формате Arrow: чтение всех колонок против проекции двух колонок
и фильтр, который сервер применяет к батчам до отправки клиенту.

Сколько байт реально прошло по сети, скрипт меряет счётчиком интерфейса lo в /proc/net/dev:
клиент и кластер на одной машине, поэтому весь их трафик идёт через loopback.

Запуск: python log_table_projection.py [--bootstrap localhost:9123] [--days 10] [--rows-per-day 20000]
"""
import argparse
import asyncio
import random
import time

import fluss
import pyarrow as pa

DB = "shop"
TABLE = "clicks"


async def connect(bootstrap: str) -> fluss.FlussConnection:
    """Подключение к кластеру и ожидание, пока зарегистрируется TabletServer."""
    deadline = time.monotonic() + 90
    while True:
        try:
            conn = await fluss.FlussConnection.create(fluss.Config({"bootstrap.servers": bootstrap}))
            nodes = await conn.get_admin().get_server_nodes()
            if any("Tablet" in n.server_type for n in nodes):
                return conn
            await conn.close()
        except Exception as e:  # кластер ещё поднимается
            last = e
        if time.monotonic() > deadline:
            raise RuntimeError(f"кластер не готов за 90 с: {last!r}")
        await asyncio.sleep(1)


def lo_bytes() -> int:
    """Байты через loopback (rx), Linux. На другой ОС вернёт -1."""
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if line.strip().startswith("lo:"):
                    return int(line.split(":", 1)[1].split()[0])
    except OSError:
        pass
    return -1


def make_day(day: int, rows: int, first_id: int, rnd: random.Random) -> pa.Table:
    """Одна пачка кликов за день: 12 колонок, из них несколько широких строковых."""
    pages = [f"/catalog/item/{i}" for i in range(500)]
    agents = [f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/{120 + i}.0 Safari/537.36" for i in range(40)]
    ids = range(first_id, first_id + rows)
    return pa.table({
        "event_id": pa.array(ids, pa.int64()),
        "user_id": pa.array([rnd.randrange(50_000) for _ in ids], pa.int64()),
        "event_day": pa.array([day] * rows, pa.int32()),
        "event_type": pa.array([rnd.choice(["view", "click", "add_to_cart"]) for _ in ids]),
        "url": pa.array([rnd.choice(pages) for _ in ids]),
        "referrer": pa.array([f"https://search.example/?q={rnd.randrange(10_000)}" for _ in ids]),
        "user_agent": pa.array([rnd.choice(agents) for _ in ids]),
        "ip": pa.array([f"10.{rnd.randrange(256)}.{rnd.randrange(256)}.{rnd.randrange(256)}" for _ in ids]),
        "country": pa.array([rnd.choice(["RU", "KZ", "BY", "AM", "UZ"]) for _ in ids]),
        "session_id": pa.array([f"s{rnd.getrandbits(64):016x}" for _ in ids]),
        "price": pa.array([round(rnd.uniform(1, 500), 2) for _ in ids], pa.float64()),
        "payload": pa.array([f'{{"ab":"v{rnd.randrange(4)}","pos":{rnd.randrange(60)},"t":{rnd.random():.6f}}}' for _ in ids]),
    })


async def read_all(table: fluss.FlussTable, end: int, scan: fluss.TableScan) -> tuple[int, int, int, float, list[int]]:
    """Читает бакет 0 с начала до конца лога. Возвращает строки, батчи, байты по lo, секунды, дни."""
    scanner = await scan.create_record_batch_log_scanner()
    scanner.subscribe(0, fluss.EARLIEST_OFFSET)
    rows = batches = 0
    days: set[int] = set()
    lo0, t0 = lo_bytes(), time.perf_counter()
    t_last = t0  # время последнего непустого ответа: хвост пустых опросов в замер не входит
    last, idle = -1, 0
    while last + 1 < end and idle < 5:
        got = await scanner.poll_record_batch(1000)
        if not got:
            idle += 1
            continue
        idle = 0
        t_last = time.perf_counter()
        for b in got:
            rows += b.batch.num_rows
            batches += 1
            last = max(last, b.last_offset)
            if "event_day" in b.batch.schema.names:
                days.update(b.batch.column("event_day").unique().to_pylist())
    return rows, batches, lo_bytes() - lo0, t_last - t0, sorted(days)


async def main(bootstrap: str, n_days: int, per_day: int) -> None:
    conn = await connect(bootstrap)
    admin = conn.get_admin()

    # 1. Таблица без первичного ключа это Log Table: только добавление, формат лога Arrow.
    # Две одинаковые таблицы: clicks с настройками по умолчанию и clicks_stats, где включена
    # колоночная статистика по event_day (по умолчанию Fluss её не собирает).
    rnd = random.Random(42)
    days = [make_day(day, per_day, (day - 1) * per_day, rnd) for day in range(1, n_days + 1)]
    await admin.create_database(DB, ignore_if_exists=True)
    tables = {}
    for name, props in ((TABLE, {}), (TABLE + "_stats", {"table.statistics.columns": "event_day"})):
        path = fluss.TablePath(DB, name)
        await admin.drop_table(path, ignore_if_not_exists=True)
        await admin.create_table(path, fluss.TableDescriptor(fluss.Schema(days[0].schema), bucket_count=1, properties=props))
        table = await conn.get_table(path)
        info = await admin.get_table_info(path)
        print(f"таблица {path.table_path_str()}: колонок {info.get_column_count()}, "
              f"первичный ключ {info.get_primary_keys() or 'нет'}, бакетов {info.num_buckets}, свойства {info.get_properties()}")

        # 2. Запись: каждый день отдельной пачкой с flush, чтобы батчи лога не смешивали дни
        writer = table.new_append().create_writer()
        t0 = time.perf_counter()
        for day_table in days:
            writer.write_arrow(day_table)
            await writer.flush()
        end = (await admin.list_offsets(path, [0], fluss.OffsetSpec.latest()))[0]
        print(f"  записано {n_days * per_day} строк за {n_days} дней, {time.perf_counter() - t0:.1f} с, офсеты 0..{end - 1}")
        tables[name] = (table, end)

    table, end = tables[TABLE]
    # 3. Полное чтение: сервер отдаёт все 12 колонок
    rows, batches, net, sec, _ = await read_all(table, end, table.new_scan())
    print(f"\n--- все 12 колонок:      {rows} строк, {batches} батчей, по сети {net / 2**20:6.2f} МиБ, {sec:.2f} с")
    full_net = net

    # 4. Проекция: просим две колонки, сервер вырезает их из колоночного Arrow-лога сам
    rows, batches, net, sec, _ = await read_all(table, end, table.new_scan().project_by_name(["user_id", "event_day"]))
    print(f"--- проекция 2 колонок:  {rows} строк, {batches} батчей, по сети {net / 2**20:6.2f} МиБ, {sec:.2f} с"
          f"  ({net / full_net:.1%} от полного чтения)")

    # 5. Фильтр по дню: сервер отбрасывает батчи, в которых по статистике нужного дня быть не может.
    # Отбор консервативный: в пришедших батчах могут быть и чужие строки, поэтому в рабочем коде
    # предикат повторяют на клиенте. Здесь печатаем, какие дни реально пришли.
    day = n_days // 2
    for name, (t, e) in tables.items():
        scan = t.new_scan().project_by_name(["user_id", "event_day"]).filter(fluss.col("event_day") == day)
        rows, batches, net, sec, seen = await read_all(t, e, scan)
        print(f"--- фильтр event_day={day}, {name:<12}: {rows} строк, {batches} батчей, по сети {net / 2**20:5.2f} МиБ,"
              f" дни в ответе {seen}")

    await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", default="localhost:9123")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--rows-per-day", type=int, default=20000)
    a = ap.parse_args()
    asyncio.run(main(a.bootstrap, a.days, a.rows_per_day))
