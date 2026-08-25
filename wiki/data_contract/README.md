# Контракт данных (Data Contract)

Код к статье [Контракт данных (Data Contract)](https://bigdataschool.ru/wiki/data_contract/).

Демо показывает контракт данных как рабочий артефакт, а не как страницу в вики: документ ODCS
3.1.0 лежит рядом с кодом, проверяется автоматически и роняет сборку, когда продюсер меняет
схему несовместимо.

## Состав

| Файл | Что внутри |
|---|---|
| `orders_contract.yaml` | Контракт ODCS 3.1.0 на таблицу `orders`: блоки описания, схемы с физическими типами, правил качества, сервера и SLA |
| `db_setup.py` | Создаёт демо-базу `contract_demo`, пересоздаёт таблицу `orders` в схеме контракта и наполняет её 5000 строк |
| `break_schema.py` | Несовместимое изменение схемы на стороне продюсера: тип суммы заказа и переименование колонки |
| `RUNBOOK.md` | Пошаговое воспроизведение с ожидаемым выводом на каждом шаге |

## Окружение

Python 3.12, `datacontract-cli` 1.1.1 с экстрой `postgres`, `open-data-contract-standard` 3.1.2,
локальный PostgreSQL 18.

## Как запустить

```bash
python3 -m venv .venv
./.venv/bin/python3 -m pip install "datacontract-cli[postgres]"
export DATACONTRACT_POSTGRES_USERNAME=<ваш_пользователь>
export DATACONTRACT_POSTGRES_PASSWORD=<ваш_пароль>

./.venv/bin/python3 db_setup.py
./.venv/bin/datacontract lint orders_contract.yaml
./.venv/bin/datacontract test orders_contract.yaml
./.venv/bin/datacontract export sql --dialect postgres orders_contract.yaml

./.venv/bin/python3 break_schema.py
./.venv/bin/datacontract test orders_contract.yaml   # ожидается 🔴 и код возврата 1
./.venv/bin/python3 db_setup.py                      # вернуть схему
```

Подробности по каждому шагу, ожидаемый вывод и типовые грабли лежат в `RUNBOOK.md`.
