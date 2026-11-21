# duckdb==2.0.0, pandas==2.3.3, pyarrow==22.0.0 | собственный код демо, проверен прогоном на DuckDB 2.0.0 LTS
"""Шаг 1. Проверяем окружение: версии пакетов и настройки движка по умолчанию."""
import platform
from importlib.metadata import version

import duckdb

EXPECTED = {"duckdb": "2.0.0", "pandas": "2.3.3", "pyarrow": "22.0.0"}

print(f"python3 {platform.python_version()} | {platform.system()} {platform.machine()}")

# Сверяем установленные версии с пинами из requirements.txt
mismatch = False
for pkg, expected in EXPECTED.items():
    got = version(pkg)
    mark = "ok" if got == expected else f"ОЖИДАЛОСЬ {expected}"
    mismatch |= got != expected
    print(f"{pkg}=={got} [{mark}]")


def scalar(con: duckdb.DuckDBPyConnection, sql: str):
    # В DuckDB 2.0 у relation нет fetchone(): берём первую строку из fetchall()
    return con.sql(sql).fetchall()[0][0]


# DuckDB работает внутри процесса: подключение к базе в памяти не поднимает никакого сервера
con = duckdb.connect()
print("SELECT version() ->", scalar(con, "SELECT version()"))
# Число потоков по умолчанию равно числу ядер, лимит памяти около 80% RAM
print("threads =", scalar(con, "SELECT current_setting('threads')"))
print("memory_limit =", scalar(con, "SELECT current_setting('memory_limit')"))
con.close()

if mismatch:
    print("Версии не совпадают с requirements.txt, цифры прогона могут отличаться")
    raise SystemExit(1)
