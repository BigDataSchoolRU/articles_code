# RUNBOOK: Vortex vs Parquet на одном датасете

## Окружение

- Linux или macOS, Python 3.11+ (wheels vortex-data 0.93.0 собраны под cp311-abi3).
- Около 3 ГБ свободной памяти и 2 ГБ диска под `data/`.
- Сервисы, Docker и Java не нужны. Данные синтетические, генерируются в скриптах (5 млн строк).
- Переменные окружения не нужны. Для 04 нужен доступ в интернет к репозиторию расширений DuckDB.

## Шаг 1. Виртуальное окружение

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

В выводе: `Successfully installed vortex-data-0.93.0 pylance-14.0.3 pyarrow-21.0.0 duckdb-2.0.1 ...`. Шаг прошёл, если `.venv/bin/python -c "import vortex, lance, duckdb"` молчит.

## Шаг 2. Запись и размер

```bash
.venv/bin/python 01_write_size.py
```

В выводе таблица `format / path / write_med_s / size_MiB / x_parquet` на четыре строки: parquet, vortex, lance, arrow_ipc. У parquet `x_parquet` равен 1.00, у arrow_ipc он заметно больше. Шаг прошёл, если код выхода 0 и в `data/` лежат orders.parquet, orders.vortex, orders.lance, orders.arrow.

## Шаг 3. Полный скан и фильтр

```bash
.venv/bin/python 02_scan_filter.py
```

В выводе для каждого формата медиана полного скана, число строк 5000000, медиана скана с фильтром и число строк после фильтра. Шаг прошёл, если число строк после фильтра одинаково во всех четырёх строках.

## Шаг 4. Случайный доступ

```bash
.venv/bin/python 03_random_access.py
```

В выводе число row group в data/orders.parquet и таблица `format / N / take_med_ms / rows` для N=10 и N=1000. Шаг прошёл, если `rows` равно N во всех строках.

## Шаг 5. DuckDB по Parquet и Vortex

```bash
.venv/bin/python 04_duckdb_vortex.py
```

В выводе версия duckdb, медиана и топ-3 городов для parquet и для vortex, затем `результаты совпадают: True`. Код выхода 2 со строкой `ОГРАНИЧЕНИЕ` значит, что расширение vortex для этой версии DuckDB не установилось.

## Шаг 6. Прогон целиком

```bash
.venv/bin/python selfcheck.py
```

В выводе первая строка с датой и версией python3, затем блоки `DEMO <файл>` с кодом выхода каждого. Последняя строка `итого: 4 из 4 демо с кодом 0`. Файл `.status` содержит код 0 и время.

## Если не так

- `ERROR: No matching distribution found for vortex-data==0.93.0`: Python ниже 3.11 или неподдерживаемая платформа. Возьмите Python 3.11+.
- `ОШИБКА vortex: AttributeError ...` или `TypeError ... к Arrow`: API Python-библиотеки Vortex поменялся. Формат файла стабилен, API нет. Сверьте имена `vortex.io.write`, `vortex.open(...).scan` с документацией вашей версии.
- `ОГРАНИЧЕНИЕ: расширение vortex ...`: нет сети или расширение не опубликовано под эту версию DuckDB. Сравнение в Python (шаги 2-4) от этого не зависит.
- Процесс убит по памяти: уменьшите `ROWS` в начале каждого скрипта и удалите `data/`, чтобы файлы пересоздались.
- Цифры сильно скачут между запусками: закройте фоновые задачи, запустите повторно; медиана из 5 повторов сглаживает разброс, но не убирает влияние кэша ОС.
