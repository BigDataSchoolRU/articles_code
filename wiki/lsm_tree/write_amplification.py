# LevelDB 1.23_2 (Homebrew) + snappy 1.2.2 + plyvel 1.5.1, python3.12, прогнано на стенде 2026-09-04
"""
Write amplification и space amplification компакции LSM-дерева на примере LevelDB.

Сценарий: один и тот же набор ключей перезаписывается несколько раз (типичный
паттерн для key-value хранилища — обновления, а не только вставки). Каждая
перезапись физически лежит в новом SST-файле, пока фоновая компакция не сольёт
уровни и не выбросит устаревшие версии ключа.

leveldb.stats после серии записей даёт кумулятивные Read(MB)/Write(MB) по каждому
уровню за счёт компакций (не считая изначальный флаш memtable->L0, он тоже
попадает в строку уровня 0). Сумма Write(MB) по всем уровням — это физические
байты, ушедшие на диск сверх одного логического Put. Отношение этой суммы к
логическому объёму записи приложением — write amplification.

compression=None специально: цель — увидеть чистый эффект компакции, не смешивая
его с эффектом сжатия (снижает объём независимо от компакции и исказил бы ratio).
"""
import os
import random
import shutil

import plyvel

DB_PATH = "/tmp/lsm_tree_demo_write_amp"
WRITE_BUFFER_SIZE = 64 * 1024
VALUE_SIZE = 200
N_KEYS = 5000
UPDATES = 8  # сколько раз перезаписываем весь набор ключей


def parse_stats(stats_text):
    """Разбирает таблицу leveldb.stats в список (level, write_mb) по непустым строкам уровней."""
    rows = []
    for line in stats_text.splitlines():
        parts = line.split()
        if len(parts) == 6 and parts[0].isdigit():
            level, files, size_mb, time_s, read_mb, write_mb = parts
            rows.append((int(level), int(write_mb)))
    return rows


def dir_size_bytes(path):
    total = 0
    for name in os.listdir(path):
        fp = os.path.join(path, name)
        if os.path.isfile(fp):
            total += os.path.getsize(fp)
    return total


def main():
    shutil.rmtree(DB_PATH, ignore_errors=True)
    db = plyvel.DB(
        DB_PATH,
        create_if_missing=True,
        write_buffer_size=WRITE_BUFFER_SIZE,
        compression=None,
    )

    random.seed(42)
    value = bytes(random.getrandbits(8) for _ in range(VALUE_SIZE))
    keys = [f"key{i:08d}".encode() for i in range(N_KEYS)]

    logical_bytes = 0
    for update_round in range(UPDATES):
        random.shuffle(keys)  # порядок перемешиваем, чтобы не спамить одну и ту же соседнюю область
        for k in keys:
            db.put(k, value)
            logical_bytes += len(k) + len(value)

    print(f"=== ПРИЛОЖЕНИЕ ЛОГИЧЕСКИ ЗАПИСАЛО {logical_bytes} БАЙТ ({UPDATES} перезаписей x {N_KEYS} ключей) ===")

    stats_text = db.get_property(b"leveldb.stats").decode()
    print("--- leveldb.stats ---")
    print(stats_text)

    rows = parse_stats(stats_text)
    total_compaction_write_mb = sum(write_mb for _, write_mb in rows)
    total_compaction_write_bytes = total_compaction_write_mb * 1024 * 1024

    print("По уровням Write(MB):", rows)
    print(f"Суммарно физических байт записано компакцией: {total_compaction_write_bytes} "
          f"({total_compaction_write_mb} MB, округление leveldb.stats до целых MB)")

    if total_compaction_write_bytes > 0:
        write_amp = total_compaction_write_bytes / logical_bytes
        print(f"Write amplification (физическая запись компакцией / логическая запись приложения): {write_amp:.2f}x")
    else:
        print("Компакция ещё не отработала на этом объёме — write amplification не измерен.")

    final_disk_bytes = dir_size_bytes(DB_PATH)
    space_ratio = final_disk_bytes / logical_bytes
    print()
    print(f"=== ИТОГОВЫЙ РАЗМЕР НА ДИСКЕ ПОСЛЕ КОМПАКЦИИ: {final_disk_bytes} байт ===")
    print(f"Отношение к логически записанному объёму: {space_ratio:.3f} "
          "(меньше 1.0 — компакция выбросила устаревшие версии перезаписанных ключей)")

    db.close()
    shutil.rmtree(DB_PATH, ignore_errors=True)


if __name__ == "__main__":
    main()
