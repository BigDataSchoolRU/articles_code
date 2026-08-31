# plyvel 1.5.1 поверх LevelDB 1.23 (Homebrew), прогнано на стенде 2026-08-31
"""Базовые операции LevelDB через plyvel: Put/Get/Delete, атомарный write batch,
снапшот для консистентного чтения и итерация по диапазону ключей."""
import shutil

import plyvel

DB_PATH = "/tmp/leveldb_demo_basic"


def main():
    shutil.rmtree(DB_PATH, ignore_errors=True)
    db = plyvel.DB(DB_PATH, create_if_missing=True)

    # --- путь записи и чтения: Put/Get ---
    db.put(b"user:001", b"Alice")
    db.put(b"user:002", b"Bob")
    db.put(b"user:003", b"Carol")
    print("get user:002 =", db.get(b"user:002"))

    # --- атомарный write batch: несколько операций одной транзакцией ---
    # либо применяются все, либо ни одной — важно при сбое посреди записи
    with db.write_batch() as batch:
        batch.put(b"user:004", b"Dave")
        batch.delete(b"user:002")
    print("после batch: user:002 =", db.get(b"user:002"), ", user:004 =", db.get(b"user:004"))

    # --- снапшот: согласованное чтение на момент создания ---
    # снапшот не видит записи, сделанные после его создания, даже той же db-ручкой
    snapshot = db.snapshot()
    db.put(b"user:005", b"Erin")
    print("снапшот не видит user:005:", snapshot.get(b"user:005"))
    print("текущая db видит user:005:", db.get(b"user:005"))
    snapshot.close()

    # --- итерация по диапазону ключей (упорядоченность — ключевое свойство LevelDB) ---
    print("диапазон ключей user:001 .. user:004 (stop не включён):")
    for key, value in db.iterator(start=b"user:001", stop=b"user:004"):
        print(" ", key, value)

    db.close()
    shutil.rmtree(DB_PATH, ignore_errors=True)


if __name__ == "__main__":
    main()
