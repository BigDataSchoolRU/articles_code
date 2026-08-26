# RUNBOOK: семантический слой на dbt + MetricFlow

Демонстрирует принцип работы семантического слоя: описываем сущность, измерения и метрики
один раз в YAML, а MetricFlow сам компилирует запрос метрики в SQL под конкретный вопрос.
Работает полностью локально, без dbt Cloud — используется open-source движок MetricFlow.

## Окружение

- Python 3.12
- PostgreSQL 18 (подойдёт любая версия 13+), запущен локально на порту 5432,
  пользователь с правом создавать базы
- Пакеты: `dbt-core==1.12.3`, `dbt-postgres==1.11.0`, `dbt-metricflow==0.14.0`
  (тянет `metricflow==0.212.0`)

Замените `techfriends` в `profiles.yml` на своего пользователя Postgres. Если у вас настроен
пароль, впишите его в поле `password`.

## Шаг 1. Установка

```bash
python3 -m venv .venv
./.venv/bin/pip install dbt-core dbt-postgres dbt-metricflow
```

Проверка: `./.venv/bin/dbt --version` должен показать установленный плагин `postgres`.

## Шаг 2. Демо-база

```bash
./.venv/bin/python3 db_setup.py
```

Должно быть в выводе: `База semantic_layer_demo создана, таблица orders заполнена.`
Скрипт можно перезапускать — база каждый раз пересоздаётся.

## Шаг 3. Материализация моделей

```bash
export DBT_PROFILES_DIR=.
./.venv/bin/dbt build
```

В выводе — `PASS=2 ... TOTAL=2`: staging-модель `stg_orders` и календарная модель
`metricflow_time_spine`. Вторая обязательна: без time spine с гранулярностью не крупнее дня
MetricFlow отказывается парсить проект с ошибкой про отсутствующую time spine model.

## Шаг 4. Запрос метрики

```bash
./.venv/bin/mf query --metrics total_revenue --group-by metric_time__month
```

В выводе — таблица «месяц / суммарная выручка» за 2025-2026 годы. Столбец `metric_time__month`
собирается автоматически из измерения `order_date`, объявленного как `agg_time_dimension`.

## Шаг 5. Смотрим сгенерированный SQL

```bash
./.venv/bin/mf query --metrics completion_rate --group-by order_id__region --explain
```

Флаг `--explain` не выполняет запрос, а печатает SQL, который MetricFlow построил на лету:
подзапрос к `stg_orders`, агрегация по региону и деление одной суммы на другую для
ratio-метрики `completion_rate`. Материализованной таблицы под эту метрику нет — SQL
собирается заново на каждый вызов.

Чтобы увидеть уже сами данные, уберите `--explain`:

```bash
./.venv/bin/mf query --metrics completion_rate --group-by order_id__region
```

## Если не так

- **`The semantic layer requires a time spine model`** — в проекте нет модели с конфигом
  `time_spine`, либо у неё гранулярность крупнее дня. Проверьте `models/_time_spine.yml`.
- **`does not match any of the available group-by-items`** — имя измерения указано без
  префикса сущности. Список валидных имён MetricFlow печатает в том же сообщении об ошибке;
  для измерений сущности `order_id` это, например, `order_id__region`, а не просто `region`.
- **`The metric X does not exist but was referenced by metric Y`** — в ratio-метрике
  `numerator`/`denominator` должны ссылаться на имена **метрик**, а не на measures напрямую.
  Заведите под measure отдельную simple-метрику и сошлитесь на неё.
- **`connection to server ... failed`** в `dbt debug` — проверьте, что Postgres запущен
  (`pg_isready`) и что пользователь/пароль в `profiles.yml` совпадают с вашими.
