# RUNBOOK: Active metadata на событиях PostgreSQL 18

Пошаговый прогон демо к статье [Active metadata](https://bigdataschool.ru/wiki/active_metadata/).
Один контейнер PostgreSQL 18.6 играет сразу три роли: источник данных, источник событий метаданных
и хранилище графа метаданных (схема `meta`). Слушатель на Python играет роль движка правил и
действий. В продакшене эти роли разнесены: каталог (DataHub, OpenMetadata и похожие), шина событий
(обычно Kafka) и отдельный сервис действий. Здесь всё в одной базе, чтобы цикл
«изменение -> событие -> правило -> действие -> запись в граф» был виден целиком.

## Окружение

| Компонент | Версия |
|---|---|
| PostgreSQL | 18.6, образ `postgres:18.6` |
| Python | 3.10 или новее, проверено на 3.12.3 |
| psycopg | 3.3.8, `psycopg[binary]` со встроенной libpq 18 |
| Docker | с плагином Compose |

Сервер слушает `127.0.0.1:55441`, пользователь и пароль `demo`/`demo`, база `demo`. Если порт
занят, поменяйте его в `docker-compose.yml` и задайте строку подключения:

```bash
export META_DSN="host=127.0.0.1 port=<порт> user=demo password=demo dbname=demo"
```

Весь прогон занимает около 15 секунд. Миллисекунды задержек у вас будут другими, состав событий,
теги, права и алерты совпадут.

## Как устроен источник событий

`setup.sql` создаёт две функции и два event trigger:

| Триггер | Событие | Что берёт | Что пишет |
|---|---|---|---|
| `meta_ddl_end` | `ddl_command_end` | `pg_event_trigger_ddl_commands()` | тип и имя объекта, состав колонок на момент события, для представления колонки, которые оно читает |
| `meta_sql_drop` | `sql_drop` | `pg_event_trigger_dropped_objects()` | удалённые таблицы, представления и колонки, флаг `original` (назван в команде или снесён каскадом) |

Обе функции пишут строку в `meta.events` и вызывают `pg_notify('meta_events', id)`. В уведомлении
только id: payload `NOTIFY` ограничен 8000 байт, а строка в журнале остаётся, даже если слушатель
в этот момент не подключён. Какие колонки читает представление, функция `meta.view_reads()` берёт
из `pg_depend` по правилу перезаписи представления.

## Шаг 1. Поднять сервер и окружение Python

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
docker compose exec -T pg psql -U demo -d demo -XAtc \
  "SELECT evtname || ' ' || evtevent || ' ' || evtfoid::regproc FROM pg_event_trigger ORDER BY 1"
```

Ожидаемо: `Container active-metadata-pg  Healthy` и два триггера:

```
meta_ddl_end ddl_command_end meta.on_ddl_end
meta_sql_drop sql_drop meta.on_sql_drop
```

Если триггеров нет, `setup.sql` не выполнился: он срабатывает только на пустом томе. Сделайте
`docker compose down -v` и поднимите заново.

## Шаг 2. Пассивный каталог против событий

```bash
.venv/bin/python passive_vs_active.py
```

Каталог дважды обходит `information_schema.columns`. Между обходами миграция добавляет колонку
`promo_code`, пишет в неё значение, удаляет её и добавляет `phone`:

```
обход 1: ['raw.customers.city', 'raw.customers.id', 'raw.customers.name']
обход 2: ['raw.customers.city', 'raw.customers.id', 'raw.customers.name', 'raw.customers.phone']
пассивный каталог видит: добавлено ['raw.customers.phone'] удалено []
```

Слушатель за то же время получил четыре события:

```
#1 ddl_command_end ALTER TABLE  app=etl_migration  table raw.customers колонки=['id', 'name', 'city', 'promo_code']
#2 sql_drop        ALTER TABLE  app=etl_migration  table column raw.customers.promo_code
#3 ddl_command_end ALTER TABLE  app=etl_migration  table raw.customers колонки=['id', 'name', 'city']
#4 ddl_command_end ALTER TABLE  app=etl_migration  table raw.customers колонки=['id', 'name', 'city', 'phone']
```

Шаг прошёл, если обход не заметил `promo_code`, а в событиях она есть. Обратите внимание: событие
`ddl_command_end` говорит «изменена таблица `raw.customers`», но не говорит, какая колонка
добавлена. Это видно только сравнением состава колонок с тем, что каталог знал раньше. Удаление
колонки, наоборот, приходит точно: `sql_drop` называет её по имени. `UPDATE` события не даёт,
event trigger срабатывает только на DDL.

Дальше в том же выводе два свойства доставки:

```
уведомлений после ROLLBACK: 0; строк в журнале про tmp_flag: 0
уведомлений после переподключения за 2.0 с: 0
догоняем по журналу meta.events с id > 4: 1
  #6 ddl_command_end ALTER TABLE  app=etl_migration  table raw.customers колонки=['id', 'name', 'city', 'phone', 'birth_date']
```

Откаченный `ALTER TABLE` не дал ни уведомления, ни строки журнала: уведомление уходит только после
коммита. Слушатель, который был отключён во время миграции, после переподключения не получил ничего,
событие нашлось только в журнале. Номер `#5` занял откаченный `ALTER TABLE`: последовательность не
откатывается, поэтому в id бывают дыры.

## Шаг 3. Правила и действия

```bash
.venv/bin/python active_actions.py
```

Каталог снимает исходное состояние одним обходом, подписывается на канал, и дальше миграция идёт
шагами. После каждого шага слушатель обрабатывает пришедшие события.

Новая колонка `email` получает тег по имени:

```
>>> ALTER TABLE raw.customers ADD COLUMN email text
  событие #1 ddl_command_end ALTER TABLE от etl_migration: table raw.customers (через 7 мс после записи)
      сравнение с каталогом: добавлены ['email'], удалены []
      -> [pii_by_name] raw.customers.email: тег pii (имя колонки совпало с (email|phone|passport|birth_date))
```

Представление, которое читает `email`, получает тег и теряет `SELECT` у роли `analyst`. Тег идёт
дальше по lineage: `report.newsletter` построен над `mart.customer_contacts` и тоже закрывается.
Представление `mart.customers_by_city` читает только `city` и остаётся открытым:

```
>>> CREATE VIEW mart.customer_contacts AS SELECT id, name, email FROM raw.customers
  событие #3 ddl_command_end CREATE VIEW от etl_migration: view mart.customer_contacts (через 7 мс после записи)
      lineage: mart.customer_contacts читает ['raw.customers.email', 'raw.customers.id', 'raw.customers.name']
      -> [pii_propagation] mart.customer_contacts: тег pii (читает raw.customers.email)
      -> [pii_propagation] mart.customer_contacts: REVOKE SELECT FROM analyst
  событие #4 ddl_command_end REVOKE от active_metadata: TABLE None (через 13 мс после записи)
      пропущено фильтром: событие порождено действием самого слушателя
```

Событие `#4` породил сам слушатель: `REVOKE` тоже DDL, и event trigger его ловит. Фильтр по
`application_name` отсекает такие события, иначе действие правила может снова запустить правило.
У `REVOKE` в событии нет имени объекта: `pg_event_trigger_ddl_commands()` отдаёт для него тип
`TABLE` и пустой `object_identity`.

Проверка прав:

```
analyst SELECT mart.customers_by_city: ok, строк 2
analyst SELECT mart.customer_contacts: permission denied for view customer_contacts
analyst SELECT report.newsletter: permission denied for view newsletter
```

И окно, пока действие ещё не выполнено:

```
mart.customer_contacts: 42 мс, в это время analyst мог читать pii
report.newsletter: 40 мс, в это время analyst мог читать pii
```

Действие идёт после коммита чужой транзакции, поэтому заблокировать изменение слушатель не может,
он только реагирует. Десятки миллисекунд здесь получены на одной машине без брокера.

Удаление колонки каскадом сносит представление, и по lineage в каталоге находится внешний
потребитель, про которого база ничего не знает:

```
>>> ALTER TABLE raw.customers DROP COLUMN city CASCADE
  событие #7 sql_drop ALTER TABLE от etl_migration: table column raw.customers.city, view mart.customers_by_city (через 7 мс после записи)
      удалён table column raw.customers.city (назван в команде)
      удалён view mart.customers_by_city (снесён каскадом)
      -> [impact_on_drop] bi.city_dashboard: АЛЕРТ владельцу: сломан источник, путь raw.customers.city -> mart.customers_by_city -> bi.city_dashboard
```

Граф для этого обхода берётся из `meta.lineage`, а не из `pg_depend`: зависимости удалённого
представления исчезли из системного каталога вместе с ним. Шаг прошёл, если в итоге:

```
событий 8, из них своих отсечено 2, действий 6
теги:
  pii  raw.customers.email          имя колонки совпало с (email|phone|passport|birth_date)
  pii  mart.customer_contacts       читает raw.customers.email
  pii  report.newsletter            читает mart.customer_contacts.email, mart.customer_contacts.name
```

Тег на представлении ставится целиком, поэтому `report.newsletter` в источниках тега называет и
`name`: колонка закрытого представления считается pii, даже если сама она безобидна. Чтобы этого
не было, нужен lineage на уровне колонок вывода, а `pg_depend` знает только, какие колонки
представление читает, но не какую колонку вывода из них строит.

## Шаг 4. Убрать стенд

```bash
docker compose down -v
```

## Если не так

- **`connection refused` на 55441.** Контейнер не поднялся или порт занят. `docker compose ps`,
  при занятом порте поменяйте его в `docker-compose.yml` и задайте `META_DSN`.
- **`FATAL: the database system is shutting down` сразу после `up`.** Healthcheck проверяет сервер
  по TCP (`pg_isready -h 127.0.0.1`), не убирайте `-h`: без него `pg_isready` отвечает «готов» ещё
  во время инициализации, когда работает временный сервер только на сокете.
- **Событий нет совсем.** Проверьте, что триггеры на месте (шаг 1). Если вы правили `setup.sql`,
  его нужно применить на чистом томе: `docker compose down -v && docker compose up -d --wait`.
- **`AttributeError: 'Connection' object has no attribute 'executemany'`.** В psycopg 3
  `executemany` есть только у курсора: `conn.cursor().executemany(...)`.
- **Слушатель не получает уведомления, а журнал растёт.** Слушатель держит открытую транзакцию:
  уведомления доставляются только между транзакциями. В демо соединения открыты с `autocommit=True`.
