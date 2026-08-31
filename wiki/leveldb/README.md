# LevelDB

Код к статье https://bigdataschool.ru/wiki/leveldb/

Примеры работы с LevelDB из Python через `plyvel`: базовые операции (Put/Get/Delete,
атомарный write batch, снапшот, итерация по диапазону ключей), compaction между уровнями
LSM-дерева и восстановление после сбоя через replay log-файла.

## Состав

| Файл | Что делает |
|---|---|
| `basic_operations.py` | Put/Get/Delete, атомарный `write_batch()`, консистентное чтение через снапшот, итерация по диапазону ключей |
| `compaction_and_recovery.py` | форсирует compaction маленьким `write_buffer_size` и показывает распределение SSTable-файлов по уровням; убивает процесс-писатель `SIGKILL` посреди записи и проверяет восстановление данных из log-файла при переоткрытии базы |
| `RUNBOOK.md` | пошаговая инструкция с ожидаемым выводом, включая известную несовместимость LevelDB 1.23 (без RTTI) и стандартной сборки `plyvel` |

## Окружение

macOS (arm64), Homebrew, LevelDB 1.23, Python 3.12, `plyvel` 1.5.1.

## Как запустить

```bash
brew install leveldb snappy
CXXFLAGS="-I$(brew --prefix leveldb)/include -I$(brew --prefix snappy)/include -fno-rtti" \
LDFLAGS="-L$(brew --prefix leveldb)/lib -L$(brew --prefix snappy)/lib" \
pip install --force-reinstall --no-cache-dir --no-build-isolation plyvel

python3 basic_operations.py
python3 compaction_and_recovery.py
```

Подробности по каждому шагу, ожидаемый вывод и разбор граблей — в `RUNBOOK.md`.
