# Apache Cloudberry

Код к статье [Apache Cloudberry](https://bigdataschool.ru/wiki/apache_cloudberry/).

Четыре SQL-демо на одноузловом кластере Apache Cloudberry 2.2.0-incubating, созданном утилитой
`gpdemo`: координатор, standby-координатор, три primary-сегмента и три зеркала на одной машине.

Первое демо показывает, из каких экземпляров Postgres собран кластер. Второе раскладывает миллион
заказов по сегментам с тремя разными ключами распределения и измеряет перекос, когда ключом выбрана
колонка с тремя значениями. Третье сравнивает планы JOIN: по ключу распределения (только
`Gather Motion`) и не по нему (`Redistribute Motion` у GPORCA, `Broadcast Motion` у планировщика
Postgres), плюс JOIN с реплицированным справочником и точечный запрос на один сегмент. Четвёртое
сравнивает размер одной таблицы в форматах heap, ao_column и PAX.

## Состав

| Файл | Что делает |
|---|---|
| `01_cluster_info.sql` | `version()`, экземпляры из `gp_segment_configuration`, число primary-сегментов, оптимизатор и тип interconnect |
| `02_distribution_skew.sql` | таблицы `DISTRIBUTED BY (order_id)`, `BY (status)`, `RANDOMLY` и `REPLICATED`; строки по сегментам, политика из `gp_distribution_policy`, коэффициент перекоса из `gp_toolkit` |
| `03_explain_motion.sql` | `EXPLAIN` JOIN с Motion и без, GPORCA против планировщика Postgres, direct dispatch, `EXPLAIN ANALYZE` |
| `04_storage_formats.sql` | одна таблица в heap, `ao_column` и `pax` со сжатием zstd, размеры на диске |
| `RUNBOOK.md` | пошаговый прогон с ожидаемым выводом |

## Окружение

Ubuntu 24.04 x86_64, бинарный пакет `apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.deb` со
страницы [релиза 2.2.0-incubating](https://github.com/apache/cloudberry/releases/tag/2.2.0-incubating),
ядро PostgreSQL 14.10, оптимизатор GPORCA 4.0.0. Нужны вход по ssh на свою машину без пароля, от 8 ГБ
свободного диска, от 4 ГБ памяти и свободные порты 7000-7007. Для других ОС в релизе есть пакеты под
Ubuntu 22.04 и Rocky Linux 8/9/10.

## Как запустить

```bash
# 1. пакет: скачать, проверить, поставить
curl -sSLO https://github.com/apache/cloudberry/releases/download/2.2.0-incubating/apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.tar.gz
tar xzf apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.tar.gz
sha512sum -c apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.deb.sha512
sudo apt install --fix-broken ./apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.deb
sudo chown -R "$USER:$USER" /usr/cloudberry-db

# 2. ssh без пароля на localhost и на имя хоста, linger против RemoveIPC (подробно в RUNBOOK)
sudo loginctl enable-linger "$USER"

# 3. кластер
source /usr/local/cloudberry-db/cloudberry-env.sh
mkdir -p ~/cloudberry_demo && cd ~/cloudberry_demo && gpdemo && source gpdemo-env.sh

# 4. демо, из каталога с SQL-файлами, по порядку: 03 и 04 используют таблицы из 02
for f in 01_cluster_info.sql 02_distribution_skew.sql 03_explain_motion.sql 04_storage_formats.sql; do
  psql -X -d postgres -e -v ON_ERROR_STOP=1 -f "$f"
done
```

Остановить кластер `gpstop -a`, удалить `gpdemo -d` в каталоге, где он создавался.
