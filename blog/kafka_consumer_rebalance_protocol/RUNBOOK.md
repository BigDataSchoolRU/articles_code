# RUNBOOK: ребалансировка групп потребителей Kafka 4, classic против KIP-848

## Окружение

| Компонент | Версия |
|---|---|
| Apache Kafka | 4.3.2 (`apache/kafka:4.3.2`), три узла KRaft, broker + controller в одном процессе |
| confluent-kafka (Python) | 2.16.0, внутри librdkafka 2.16.0 |
| Java-клиент | тот, что лежит в образе Kafka (`kafka-console-consumer.sh`) |
| Python | 3.12 |

Нужно: Docker с Compose v2, около 4.5 ГБ памяти под контейнеры (лимит 1.5 ГБ на узел),
свободные порты 9092, 9094 и 9096 на 127.0.0.1, доступ в интернет для образа и пакета PyPI.
Переменные окружения не нужны. Все команды выполняются из папки с кодом.

Что настроено на брокере в `compose.yaml` и почему:

- `group.consumer.session.timeout.ms=10000` и `group.consumer.min.session.timeout.ms=6000`. Для
  нового протокола тайм-аут сессии задаёт брокер, по умолчанию 45 с с таким же минимумом.
  Classic-клиенты в демо выставляют `session.timeout.ms=10000` сами, так варианты сравнимы.
- `group.consumer.min.heartbeat.interval.ms=1000`. Сам интервал heartbeat остаётся 5000 мс по
  умолчанию, нижняя граница опущена, чтобы вариант `consumer_hb1s` мог выставить группе 1 с.

## Шаг 1. Поднять стенд

```bash
docker compose up -d --wait
docker compose exec -T kafka1 /opt/kafka/bin/kafka-topics.sh --version
```

Что в выводе: три контейнера `kafka1..3` в состоянии `Healthy`, версия `4.3.2`.

Как понять, что прошло: `docker compose ps` показывает все три узла `healthy`.

## Шаг 2. Python-клиент

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Как понять, что прошло: `.venv/bin/python -c "import confluent_kafka as c; print(c.libversion())"`
печатает `('2.16.0', ...)`.

## Шаг 3. Старые настройки на новом протоколе

```bash
.venv/bin/python old_settings_trap.py
```

Скрипт сам создаёт топик `rebalance-bench` на 12 партиций. Потом для каждой настройки
создаёт потребителя с `group.protocol=consumer` и 8 секунд читает.

Что в выводе:

- без лишних настроек и с `group.remote.assignor=range`: `назначено партиций: 12`;
- `session.timeout.ms`, `heartbeat.interval.ms`, `partition.assignment.strategy`:
  `конструктор упал: ... is not supported for group.protocol=consumer`;
- `group.remote.assignor=sticky`: конструктор проходит, потом фатальная ошибка
  `The assignor or its version range is not supported by the consumer group`;
- Java: `ConfigException: session.timeout.ms cannot be set when group.protocol=CONSUMER` и то же
  для `partition.assignment.strategy`, код выхода 1.

Как понять, что прошло: ни один вариант со старой настройкой не дошёл до чтения.

## Шаг 4. Онлайн-миграция с classic на consumer

```bash
.venv/bin/python migrate_group.py
```

Скрипт запускает продюсер на 1200 сообщений/с и группу из 4 участников classic с
`cooperative-sticky`. Затем по одному перезапускает их с `group.protocol=consumer`.

Что в выводе:

- шаг 0: `kafka-groups.sh --list` показывает `TYPE Classic`;
- с шага 1: `TYPE Consumer`, в `--describe --members --verbose` появляются `CURRENT-EPOCH`,
  `TARGET-ASSIGNMENT` и колонка `UPGRADED`: `true` у перезапущенных, `false` у старых;
- на шаге 1 (конвертация группы) несколько партиций стоят чуть больше секунды, на шагах 2-4
  строка `пауза: остановлено 0/12`;
- на шаге 4 колонка `UPGRADED` пропадает: в группе не осталось classic-участников.

Как понять, что прошло: тип группы сменился на первом же перезапуске, а чтение не встало.

## Шаг 5. Замер паузы

```bash
.venv/bin/python rebalance_bench.py 3
```

Пять вариантов по три повтора, около 25 минут. Для каждого повтора группа из 4 участников
переживает четыре события: вход пятого (`add`), его мягкий выход (`leave`), падение участника по
SIGKILL (`crash`), падение и перезапуск под тем же именем через секунду (`restart`).

Что в выводе: строка на событие в каждом повторе, в конце таблица медиан
`=== МЕДИАНЫ ПО 3 ПОВТОРАМ ===` и файл `bench_results.json`.

- `остановлено N/12` значит, что у N партиций задержка чтения превысила 1 с;
- `макс. пауза` это худшая задержка партиции;
- `отозвано` это сколько партиций отобрали колбэки `on_revoke`;
- `повторов` это сообщения, прочитанные второй раз после падения: offset ещё не был зафиксирован.

Как понять, что прошло:

- у `eager` на каждом событии все живые участники отдают все свои партиции (`отозвано 12`
  на `add` и `leave`), у остальных вариантов только те, что переезжают;
- у `eager` на `restart` останавливаются все 12 партиций;
- у `static` на `restart` пауза около 1.3-2 с, а на `leave` около 10-13 с: статический участник
  при выходе не покидает группу, и его партиции ждут тайм-аута сессии;
- у `consumer` прогрев группы около 13 с, а `leave` около 5 с: сервер сначала отзывает
  партиции, а выдаёт их новому владельцу на следующем heartbeat, по умолчанию раз в 5 с.
  У `consumer_hb1s` прогрев около 6 с, `leave` около 1 с;
- `crash` у всех вариантов около 10-11 с: это тайм-аут сессии, протокол его не сокращает.

## Шаг 6. Убрать стенд

```bash
docker compose down -v
```

## Если не так

- Узел не становится `healthy`: проверьте `docker compose logs kafka1`. Чаще всего не хватает
  памяти, каждому узлу нужно 1.5 ГБ.
- `set_group_config` в варианте `consumer_hb1s` падает с ошибкой конфигурации: брокер поднят
  без `group.consumer.min.heartbeat.interval.ms=1000`, а 1000 мс ниже минимума по умолчанию.
  Пересоздайте стенд с `down -v` и текущим `compose.yaml`.
- В `migrate_group.py` тип группы остаётся `Classic`: на брокере выставлен
  `group.consumer.migration.policy=disabled` или `downgrade`. По умолчанию `bidirectional`.
- Паузы `crash` заметно больше 11 с: проверьте, что брокер получил
  `group.consumer.session.timeout.ms=10000`, иначе новый протокол ждёт 45 с.
- Цифры отличаются от статьи на доли секунды: они зависят от машины и момента heartbeat.
  Сравнивайте варианты между собой, а не абсолютные значения.
