# Ребалансировка в Kafka 4: KIP-848 против classic

Код к статье: https://bigdataschool.ru/blog/news/kafka-consumer-rebalance-protocol/

Стенд меряет паузу в чтении, когда группа потребителей меняет состав, для пяти вариантов:
classic eager (range), classic cooperative-sticky, static membership, новый протокол consumer
(KIP-848) с настройками брокера по умолчанию и он же с heartbeat группы 1 с. Плюс онлайн-миграция
живой группы с classic на consumer и проверка старых клиентских настроек на новом протоколе.

## Файлы

| Файл | Что делает |
|---|---|
| `compose.yaml` | стенд: три узла Apache Kafka 4.3.2 в KRaft (broker + controller) |
| `producer_load.py` | топик `rebalance-bench` на 12 партиций и ровная нагрузка 1200 сообщений/с |
| `group_member.py` | участник группы в отдельном процессе и сборщик паузы по партициям |
| `rebalance_bench.py` | замер: вход, мягкий выход, падение и рестарт участника для пяти вариантов |
| `migrate_group.py` | поочерёдный перевод группы classic на `group.protocol=consumer` |
| `old_settings_trap.py` | что делают Python- и Java-клиент со старыми настройками на новом протоколе |
| `requirements.txt` | Python-клиент `confluent-kafka` |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с Compose v2, около 4.5 ГБ памяти под контейнеры, Python 3.12. Порты 9092, 9094 и 9096
публикуются только на 127.0.0.1. Тайм-аут сессии во всех вариантах 10 с: у classic его задаёт
клиент, у consumer брокер (`group.consumer.session.timeout.ms` в `compose.yaml`).

## Как запустить

1. `docker compose up -d --wait`
2. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. `.venv/bin/python old_settings_trap.py`, `.venv/bin/python migrate_group.py`,
   `.venv/bin/python rebalance_bench.py 3`; подробности в `RUNBOOK.md`.
4. `docker compose down -v`
