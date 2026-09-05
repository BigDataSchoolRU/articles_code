# LevelDB 1.23_2 (Homebrew) + snappy 1.2.2 + plyvel 1.5.1, python3.12, прогнано на стенде 2026-09-04
"""
Путь записи и путь чтения LSM-дерева на примере LevelDB.

Путь записи: Put -> WAL (.log) -> memtable (в памяти) -> при заполнении memtable
(write_buffer_size) флаш на диск отдельным SST-файлом уровня L0.

Путь чтения: Get идёт сверху вниз — сначала memtable, затем файлы L0 (могут
перекрываться по диапазону ключей, поэтому проверяются все), затем L1 и ниже
(диапазоны не пересекаются, нужен один файл на уровень). Чем больше
непрокомпакченных файлов L0, тем больше файлов заглядывает один Get —
это и есть read amplification на практике, а не только в асимптотике.
"""
import os
import random
import shutil
import time

import plyvel

DB_PATH = "/tmp/lsm_tree_demo_write_read"
WRITE_BUFFER_SIZE = 32 * 1024  # маленький специально, чтобы флаш случился быстро
VALUE_SIZE = 200
N_KEYS = 8000
PROBE_KEYS = 500
PROBE_REPEATS = 5


def list_db_files(path):
    """Раскладывает файлы каталога LevelDB по типу: WAL, SST, MANIFEST, прочее."""
    wal, sst, manifest, other = [], [], [], []
    for name in sorted(os.listdir(path)):
        if name.endswith(".log"):
            wal.append(name)
        elif name.endswith(".ldb") or name.endswith(".sst"):
            sst.append(name)
        elif name.startswith("MANIFEST"):
            manifest.append(name)
        else:
            other.append(name)
    return wal, sst, manifest, other


def num_files_at_level(db, level):
    return int(db.get_property(f"leveldb.num-files-at-level{level}".encode()))


def timed_gets(db, keys, repeats):
    t0 = time.perf_counter()
    for _ in range(repeats):
        for k in keys:
            db.get(k)
    return time.perf_counter() - t0


def main():
    shutil.rmtree(DB_PATH, ignore_errors=True)
    db = plyvel.DB(
        DB_PATH,
        create_if_missing=True,
        write_buffer_size=WRITE_BUFFER_SIZE,
        compression=None,  # без сжатия: файлы и байты на диске отражают только LSM-механику
    )

    print("=== ПУТЬ ЗАПИСИ ===")
    print("До записи:", list_db_files(DB_PATH))

    random.seed(7)
    value = bytes(random.getrandbits(8) for _ in range(VALUE_SIZE))
    keys = [f"key{i:08d}".encode() for i in range(N_KEYS)]
    random.shuffle(keys)  # случайный порядок ключей — иначе флаши сразу каскадом уедут на нижние уровни

    checkpoints = {N_KEYS // 4, N_KEYS // 2, N_KEYS}
    for i, k in enumerate(keys, start=1):
        db.put(k, value)
        if i in checkpoints:
            wal, sst, manifest, _ = list_db_files(DB_PATH)
            print(
                f"после {i} записей: WAL={wal}, SST-файлов={len(sst)}, "
                f"L0={num_files_at_level(db, 0)}, L1={num_files_at_level(db, 1)}"
            )

    print()
    print("=== СОСТОЯНИЕ УРОВНЕЙ СРАЗУ ПОСЛЕ ЗАПИСИ (leveldb.sstables) ===")
    print(db.get_property(b"leveldb.sstables").decode())

    print("=== ПУТЬ ЧТЕНИЯ: read amplification от количества файлов L0 ===")
    probe_keys = keys[:PROBE_KEYS]
    l0_before = num_files_at_level(db, 0)
    t_before = timed_gets(db, probe_keys, PROBE_REPEATS)
    print(f"L0 файлов во время замера: {l0_before}, время {PROBE_REPEATS}x{PROBE_KEYS} Get: {t_before:.4f} с")

    print("Ждём фоновую компакцию L0 -> L1...")
    for _ in range(80):
        time.sleep(0.1)
        if num_files_at_level(db, 0) <= 1:
            break
    l0_after = num_files_at_level(db, 0)

    t_after = timed_gets(db, probe_keys, PROBE_REPEATS)
    print(f"L0 файлов после компакции: {l0_after}, время {PROBE_REPEATS}x{PROBE_KEYS} Get: {t_after:.4f} с")
    print(f"Отношение (до/после): {t_before / t_after:.2f}x")

    db.close()
    shutil.rmtree(DB_PATH, ignore_errors=True)


if __name__ == "__main__":
    main()
