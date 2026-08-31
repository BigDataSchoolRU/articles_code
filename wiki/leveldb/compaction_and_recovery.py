# plyvel 1.5.1 поверх LevelDB 1.23 (Homebrew), прогнано на стенде 2026-08-31
"""Compaction между уровнями и восстановление после сбоя.

Часть 1 форсирует compaction маленьким write_buffer_size и показывает,
куда физически лёг SSTable-файл на каждом уровне.
Часть 2 убивает процесс-писатель SIGKILL посреди записи и проверяет,
что данные, попавшие в log-файл до этого момента, переживают сбой.
"""
import multiprocessing
import os
import shutil
import signal
import time

import plyvel

COMPACTION_DB_PATH = "/tmp/leveldb_demo_compaction"
CRASH_DB_PATH = "/tmp/leveldb_demo_crash"


def levels_snapshot(db, max_level=4):
    return {
        level: db.get_property(f"leveldb.num-files-at-level{level}".encode()).decode()
        for level in range(max_level)
    }


def demo_compaction():
    print("=== Compaction между уровнями ===")
    shutil.rmtree(COMPACTION_DB_PATH, ignore_errors=True)
    # маленький write_buffer_size (64 КБ вместо дефолтных 4 МБ), чтобы уложиться
    # в разумный объём данных и всё равно перейти пороги compaction из doc/impl.md
    db = plyvel.DB(COMPACTION_DB_PATH, create_if_missing=True, write_buffer_size=64 * 1024)

    t0 = time.time()
    for i in range(50_000):
        db.put(f"key{i:08d}".encode(), os.urandom(200))
    elapsed = time.time() - t0
    print(f"записано 50000 пар по ~200 байт (итого ~10 МБ) за {elapsed:.2f} с")

    print("файлов по уровням после записи:", levels_snapshot(db))
    print("db.get_property('leveldb.stats'):")
    print(db.get_property(b"leveldb.stats").decode())

    # 'leveldb.sstables' показывает физические файлы и диапазоны ключей внутри уровня
    sstables = db.get_property(b"leveldb.sstables").decode()
    print("первые строки leveldb.sstables (файл: размер [диапазон ключей]):")
    for line in sstables.splitlines()[:6]:
        print(" ", line)

    db.close()
    shutil.rmtree(COMPACTION_DB_PATH, ignore_errors=True)


def _crash_writer(path, n):
    db = plyvel.DB(path, create_if_missing=True)
    for i in range(n):
        db.put(f"k{i:06d}".encode(), b"v" * 50)
        time.sleep(0.01)
    # намеренно не вызываем db.close() — процесс убьют снаружи до этой строки


def demo_crash_recovery():
    print()
    print("=== Восстановление после сбоя ===")
    shutil.rmtree(CRASH_DB_PATH, ignore_errors=True)
    total = 500

    process = multiprocessing.Process(target=_crash_writer, args=(CRASH_DB_PATH, total))
    process.start()
    time.sleep(1.0)  # даём писателю проработать примерно секунду
    os.kill(process.pid, signal.SIGKILL)
    process.join()
    print(f"процесс-писатель убит SIGKILL, exitcode={process.exitcode}")

    # переоткрытие базы запускает восстановление: CURRENT -> MANIFEST -> replay log-файла
    db = plyvel.DB(CRASH_DB_PATH, create_if_missing=False)
    recovered = sum(1 for _ in db.iterator())
    print(f"после переоткрытия найдено записей: {recovered} из {total} (часть до момента убийства)")
    db.close()
    shutil.rmtree(CRASH_DB_PATH, ignore_errors=True)


if __name__ == "__main__":
    demo_compaction()
    demo_crash_recovery()
