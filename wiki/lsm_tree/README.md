# LSM-Tree

Код к статье [LSM-дерево (LSM-Tree): архитектура и принцип работы](https://bigdataschool.ru/wiki/lsm_tree/).

## Состав

- `write_read_path.py` — путь записи (WAL, memtable, флаш в SST, рост числа файлов
  L0) и путь чтения (замер, во сколько раз ускоряется `Get` после того, как
  фоновая компакция сливает файлы L0 в L1).
- `write_amplification.py` — измерение write amplification (по `leveldb.stats`) и
  space amplification (итоговый размер на диске против логически записанного
  объёма) на сценарии многократной перезаписи одного набора ключей.
- `RUNBOOK.md` — как поднять окружение и прогнать демо самостоятельно.

## Окружение

- LevelDB 1.23_2 и snappy 1.2.2 (Homebrew), plyvel 1.5.1, Python 3.12.
- Внешние сервисы не нужны — LevelDB встроена в процесс.

## Запуск

```bash
python3 -m venv .venv && source .venv/bin/activate
CXXFLAGS="-I$(brew --prefix leveldb)/include -I$(brew --prefix snappy)/include -fno-rtti" \
LDFLAGS="-L$(brew --prefix leveldb)/lib -L$(brew --prefix snappy)/lib" \
pip install --no-cache-dir --no-build-isolation plyvel==1.5.1

python3 write_read_path.py
python3 write_amplification.py
```

Подробности и типовые грабли — в `RUNBOOK.md`.
