# Kappa Architecture

Код к статье [Kappa Architecture](https://bigdataschool.ru/wiki/kappa_architecture/).

Пересчёт истории в Kappa Architecture на одном брокере Apache Kafka 4.3.2 и SQLite в роли serving-хранилища.
Лог заказов в Kafka хранится бессрочно (`retention.ms=-1`). Потоковая джоба v1 считает выручку по
клиентам с ошибкой: возврат прибавляет, а не вычитает. Исправленная v2 запускается рядом с v1 в новой
consumer group, читает лог с нулевого offset в свою таблицу, догоняет голову лога и дальше обрабатывает
живой поток вместе с v1. Когда лаг v2 нулевой, view, из которого читает приложение, одной транзакцией
переключается на таблицу v2, а таблица и группа v1 удаляются. Отдельный скрипт показывает предел подхода:
события, которые retention уже удалил из лога, пересчёт не увидит, и Kafka об этом не предупреждает.

## Состав

| Файл | Что делает |
|---|---|
| `docker-compose.yml` | Kafka 4.3.2 в режиме KRaft, один узел, порт `127.0.0.1:59093` |
| `requirements.txt` | `confluent-kafka==2.16.1` |
| `produce_events.py` | создаёт топик `kappa_architecture_orders` с бессрочным retention, пишет историю пачкой или живой поток с заданным темпом |
| `stream_job.py` | потоковая джоба `--version v1` или `v2`: своя consumer group, своя таблица `orders_by_customer_<версия>`, лаг раз в секунду и время догоняния |
| `switch_serving.py` | проверяет лаг целевой версии, сверяет таблицы с пересчётом напрямую из лога, показывает место, переключает view `orders_by_customer`, с `--drop-old` удаляет старую версию |
| `retention_limit.py` | топик с retention 10 с: старый сегмент удаляется, пересчёт с `earliest` молча начинается с нового начала лога |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Docker с плагином Compose, образ `apache/kafka:4.3.2`, Python 3.10 или новее (SQLite из стандартной
библиотеки), около 100 МБ на диске под лог Kafka.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python produce_events.py --count 600000 --seed 1
.venv/bin/python stream_job.py --version v1 --exit-when-caught-up
.venv/bin/python switch_serving.py --to v1
# живой поток, v1 и v2 параллельно: три терминала или фоном, см. RUNBOOK, шаг 5
.venv/bin/python switch_serving.py --to v2 --drop-old
.venv/bin/python retention_limit.py
docker compose down -v
```

Повторный прогон с нуля начинается с `docker compose down -v` и удаления `serving.db*`: consumer group
помнит свои offset'ы, и v1 без этого продолжит с места остановки.
