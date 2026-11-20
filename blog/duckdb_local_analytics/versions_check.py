# duckdb==2.0.0, pandas==2.3.3, pyarrow==22.0.0 | демо bigdataschool.ru к статье «DuckDB для локальной аналитики», код написан по брифу, вывод фиксирует прогон selfcheck.py
"""Шаг 1. Проверяем, что в окружении стоят ровно те версии, под которые написана статья.

Код выхода 1 только при расхождении версий дистрибутивов или если не импортируется duckdb.
Диагностика движка (pragma_version, настройки) печатается для справки и шаг не роняет:
любое исключение выводится с трассировкой, чтобы причину было видно в run_output.txt.
"""
import importlib
import platform
import sys
import traceback
from importlib.metadata import PackageNotFoundError, version

EXPECTED = {"duckdb": "2.0.0", "pandas": "2.3.3", "pyarrow": "22.0.0"}
# Без этих модулей демо не работают; pyarrow остальные шаги не импортируют
REQUIRED_IMPORT = {"duckdb", "pandas"}


def dist_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "не установлен"


def norm(v: str) -> tuple:
    """2.0 и 2.0.0 считаем одной версией, как это делает pip для ==."""
    parts = v.strip().split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return tuple(parts)


def try_import(name: str):
    try:
        return importlib.import_module(name), None
    except BaseException as exc:  # импорт нативного модуля может упасть чем угодно
        print(f"Импорт {name} не прошёл: {type(exc).__name__}: {exc}")
        traceback.print_exc(file=sys.stdout)
        return None, exc


def setting(con, name: str) -> str:
    """Значение настройки через duckdb_settings(), с запасным путём через current_setting()."""
    errors = []
    try:
        row = con.execute("SELECT value FROM duckdb_settings() WHERE name = ?", [name]).fetchone()
        if row is not None:
            return str(row[0])
        errors.append("настройки нет в duckdb_settings()")
    except Exception as exc:
        errors.append(f"duckdb_settings: {type(exc).__name__}: {exc}")
    try:
        row = con.execute(f"SELECT current_setting('{name}')").fetchone()
        if row is not None:
            return str(row[0])
        errors.append("current_setting вернул пустой результат")
    except Exception as exc:
        errors.append(f"current_setting: {type(exc).__name__}: {exc}")
    return "<не удалось прочитать: " + "; ".join(errors) + ">"


def engine_info(duckdb) -> None:
    """Справочная диагностика движка: ошибки печатаются, но шаг не роняют."""
    try:
        # Движок встроен в процесс: подключение без сервера, порта и пароля
        con = duckdb.connect()
    except Exception:
        print("duckdb.connect() не прошёл:")
        traceback.print_exc(file=sys.stdout)
        return
    try:
        cur = con.execute("SELECT * FROM pragma_version()")
        cols = [d[0] for d in (cur.description or [])]
        row = cur.fetchone()
        if row is None:
            print("pragma_version() вернул пустой результат")
        else:
            for i, val in enumerate(row):
                col = cols[i] if i < len(cols) else f"col{i}"
                print(f"pragma_version.{col} = {val}")
    except Exception:
        print("pragma_version() не прочитан:")
        traceback.print_exc(file=sys.stdout)

    # Настройки по умолчанию: число потоков и лимит памяти DuckDB выбирает сам
    print("threads =", setting(con, "threads"))
    print("memory_limit =", setting(con, "memory_limit"))
    try:
        con.close()
    except Exception:
        pass


def main() -> int:
    print(f"python   {platform.python_version()} ({platform.system()} {platform.machine()})")
    print(f"interpreter {sys.executable}")

    modules, import_failed = {}, []
    for name in EXPECTED:
        mod, err = try_import(name)
        modules[name] = mod
        if err is not None:
            import_failed.append(name)

    # Сверяем версии дистрибутивов, как их поставил pip; __version__ модуля печатаем для справки
    actual = {name: dist_version(name) for name in EXPECTED}
    mismatched = []
    for name, ver in actual.items():
        good = ver != "не установлен" and norm(ver) == norm(EXPECTED[name])
        if not good:
            mismatched.append(name)
        mark = "ok" if good else f"ОЖИДАЛАСЬ {EXPECTED[name]}"
        mod = modules.get(name)
        mod_ver = getattr(mod, "__version__", "?") if mod is not None else "не импортирован"
        print(f"{name:<8} {ver}  [{mark}]  (__version__ = {mod_ver})")

    if modules.get("duckdb") is not None:
        engine_info(modules["duckdb"])

    hard_import = [n for n in import_failed if n in REQUIRED_IMPORT]
    soft_import = [n for n in import_failed if n not in REQUIRED_IMPORT]
    if soft_import:
        print("Предупреждение: не импортируется", ", ".join(soft_import),
              "- остальные шаги этот модуль не используют")
    if mismatched:
        print("Версии не совпадают с requirements.txt:", ", ".join(mismatched))
    if hard_import:
        print("Не импортируются обязательные модули:", ", ".join(hard_import))
    if mismatched or hard_import:
        return 1
    print("Все версии совпадают с requirements.txt")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        traceback.print_exc(file=sys.stdout)
        rc = 1
    sys.stdout.flush()
    sys.exit(rc)
