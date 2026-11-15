# RUNBOOK: демо-кластер Apache Cloudberry 2.2.0, ключ распределения и Motion

Пошаговый прогон демо к статье [Apache Cloudberry](https://bigdataschool.ru/wiki/apache_cloudberry/).
На каждом шаге: что делаем, команда, что должно быть в выводе и как понять, что шаг прошёл.
Ожидаемый вывод снят на прогоне 2026-11-15. Числа строк по сегментам, коэффициент перекоса таблиц с
ключом, планы `EXPLAIN` и размеры таблиц совпадут, потому что данные генерируются детерминированно, а
сегмент выбирается хешем ключа. Отличаться будут только время выполнения и строки таблицы
`orders_random`: при `DISTRIBUTED RANDOMLY` раскладка случайная.

## Окружение

| Что | Версия на прогоне | Минимум |
|---|---|---|
| ОС | Ubuntu 24.04.4 LTS, x86_64 (4 vCPU, 15.7 ГБ RAM) | Ubuntu 24.04 для пакета `ubuntu24.04`; под Ubuntu 22.04 и Rocky Linux 8/9/10 в релизе есть свои пакеты |
| Apache Cloudberry | 2.2.0-incubating, build `13d3c58eaa0`, пакет `apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.deb` | |
| Ядро PostgreSQL | 14.10 (так отвечает `version()`) | |
| Оптимизатор | GPORCA 4.0.0 (`optimizer = on` по умолчанию) | |

Ресурсы. Пакет занимает около 80 МБ. Кластер `gpdemo` состоит из восьми экземпляров Postgres:
координатор, standby-координатор, три primary-сегмента и три зеркала. Сразу после создания его
каталоги занимают 1.8 ГБ, после двух прогонов всех демо 4.7 ГБ, потому что WAL пишут и primary, и
зеркала, и standby. Свободного места на диске нужно от 8 ГБ, памяти от 4 ГБ. Порты 7000-7007 должны быть
свободны.

Работаем под своим пользователем с sudo. В продакшене под кластер заводят отдельного пользователя
`gpadmin`, для одноузлового демо это не обязательно.

## Шаг 1. Пакет

Скачиваем бинарный пакет со страницы релиза и проверяем контрольную сумму. Архив содержит сам `.deb`,
его `.sha512` и подпись `.asc`.

```bash
mkdir -p ~/cloudberry_pkg && cd ~/cloudberry_pkg
curl -sSLO https://github.com/apache/cloudberry/releases/download/2.2.0-incubating/apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.tar.gz
tar xzf apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.tar.gz
sha512sum -c apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.deb.sha512
```

Ожидаемо: архив около 20 МБ, проверка печатает

```
apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.deb: OK
```

Ставим пакет командой из официальной инструкции «Installing Using RPM/DEB Package». `apt` сам
подтянет зависимости, среди них `libprotobuf32t64`, `liburing2`, `libxerces-c3.2t64`, `openssh-server`.

```bash
sudo apt install --fix-broken ./apache-cloudberry-db-incubating_2.2.0-1-ubuntu24.04_amd64.deb
sudo chown -R "$USER:$USER" /usr/cloudberry-db
```

Пакет 2.2.0 кладёт файлы в `/usr/cloudberry-db` и делает симлинк `/usr/local/cloudberry-db` на этот
каталог. Документация описывает каталог `/usr/local/cloudberry-db-<version>`, у пакета 2.2.0 путь
другой, поэтому `chown` делаем по реальному каталогу, а не по симлинку. На прогоне пакет был
распакован из `.deb` без установки в систему, и его файлы принадлежали тому же пользователю, от которого
работал кластер. `chown` выше приводит установленный пакет к такому же состоянию.

Проверка:

```bash
source /usr/local/cloudberry-db/cloudberry-env.sh
postgres --gp-version
```

```
postgres (Apache Cloudberry) 2.2.0-incubating build 13d3c58eaa0
```

## Шаг 2. SSH на свою же машину без пароля

Утилиты управления кластером (`gpinitsystem`, `gpstart`, `gpstate`) ходят на хосты сегментов по ssh,
даже когда все сегменты живут на одной машине. Нужен вход без пароля и на `localhost`, и на имя хоста.

```bash
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new localhost echo ok
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$(hostname)" echo ok
```

Шаг прошёл, если обе команды напечатали `ok` и не спросили пароль.

## Шаг 3. Чтобы кластер не умер при выходе из ssh

В Ubuntu по умолчанию включён `RemoveIPC=yes` в systemd-logind. Когда у пользователя закрывается
последняя сессия, logind удаляет его объекты разделяемой памяти и файлы в `/dev/shm`. Экземпляры
Postgres, запущенные от обычного пользователя, после этого падают. Включаем linger: пользователь
считается вошедшим в систему постоянно, и чистка не срабатывает.

```bash
sudo loginctl enable-linger "$USER"
loginctl show-user "$USER" -p Linger
```

```
Linger=yes
```

Если работаете в графической сессии и не выходите из неё, шаг можно пропустить. После экспериментов
linger выключается командой `sudo loginctl disable-linger "$USER"`.

## Шаг 4. Кластер gpdemo

`gpdemo` из комплекта утилит создаёт кластер на одной машине одной командой: координатор на порту
7000, standby на 7001, три primary-сегмента на 7002-7004 и их зеркала на 7005-7007. Данные кладутся в
`./datadirs` текущего каталога.

```bash
source /usr/local/cloudberry-db/cloudberry-env.sh
mkdir -p ~/cloudberry_demo && cd ~/cloudberry_demo
gpdemo
source gpdemo-env.sh
```

На прогоне создание заняло 19 секунд. В конце вывода:

```
gpinitsystem returned: 0
...
  Optimizer state .. :  on
...
 GPOPT version: 4.0.0, Xerces version: 3.2.4
```

`gpdemo-env.sh` выставляет `PGPORT=7000` и `COORDINATOR_DATA_DIRECTORY`. Его нужно подключать в каждой
новой сессии вместе с `cloudberry-env.sh`.

Проверка:

```bash
gpstate -b
```

```
   Coordinator instance                                      = Active
   Standby coordinator state                                 = Standby host passive
   Total segment instance count from metadata                = 6
   Total primary segments                                    = 3
   Total primary segment valid (at coordinator)              = 3
   Total mirror segments                                     = 3
   Total mirror segment valid (at coordinator)               = 3
```

## Шаг 5. Состав кластера

Файлы `01_*.sql`-`04_*.sql` лежат рядом с этим RUNBOOK. Запускаем из каталога с ними:

```bash
psql -X -d postgres -e -v ON_ERROR_STOP=1 -f 01_cluster_info.sql
```

Ожидаемо:

```
 PostgreSQL 14.10 (Apache Cloudberry 2.2.0-incubating build 13d3c58eaa0) on x86_64-pc-linux-gnu, ...

 content | role | preferred_role | mode | status | port
---------+------+----------------+------+--------+------
      -1 | p    | p              | n    | u      | 7000
      -1 | m    | m              | s    | u      | 7001
       0 | p    | p              | s    | u      | 7002
       0 | m    | m              | s    | u      | 7005
       1 | p    | p              | s    | u      | 7003
       1 | m    | m              | s    | u      | 7006
       2 | p    | p              | s    | u      | 7004
       2 | m    | m              | s    | u      | 7007

 primary_segments
------------------
                3

 optimizer
-----------
 on

 gp_interconnect_type
----------------------
 udpifc
```

Шаг прошёл, если у всех восьми строк `status = u`, а у сегментов `mode = s` (зеркала синхронизированы).

## Шаг 6. Ключ распределения и перекос

```bash
psql -X -d postgres -e -v ON_ERROR_STOP=1 -f 02_distribution_skew.sql
```

Скрипт создаёт миллион заказов в трёх таблицах с одинаковыми строками и разными ключами
распределения. Ожидаемо:

```
    table_name    | policytype | distkey
------------------+------------+---------
 orders_by_id     | p          | 1
 orders_by_status | p          | 3
 orders_random    | p          |

    table_name    | gp_segment_id | row_count
------------------+---------------+-----------
 orders_by_id     |             0 |    333167
 orders_by_id     |             1 |    332791
 orders_by_id     |             2 |    334042
 orders_by_status |             0 |    800000
 orders_by_status |             1 |    100000
 orders_by_status |             2 |    100000
 orders_random    |             0 |    ~333000
 ...

  status   | gp_segment_id | row_count
-----------+---------------+-----------
 cancelled |             2 |    100000
 delivered |             0 |    800000
 shipped   |             1 |    100000

    table_name    | skew_coefficient
------------------+------------------
 orders_by_id     |             0.19
 orders_by_status |           121.24
 orders_random    |             ~0.2

 segment | row_count
---------+-----------
       0 |         3
       1 |         3
       2 |         3
```

Что видно: при ключе `order_id` строки легли почти поровну. При ключе `status` все 800 000 заказов со
статусом `delivered` ушли на сегмент 0, потому что одно значение ключа всегда попадает на один
сегмент. Реплицированный справочник `regions` лежит целиком, по три строки, на каждом сегменте.

## Шаг 7. План запроса и Motion

```bash
psql -X -d postgres -e -v ON_ERROR_STOP=1 -f 03_explain_motion.sql
```

JOIN по ключу распределения обеих таблиц, `orders_by_customer` и `customers`. Строки одного клиента
уже лежат на одном сегменте, пересылка нужна только для сбора результата:

```
 Finalize Aggregate
   ->  Gather Motion 3:1  (slice1; segments: 3)
         ->  Partial Aggregate
               ->  Hash Join
                     Hash Cond: (o.customer_id = c.customer_id)
                     ->  Seq Scan on orders_by_customer o
                     ->  Hash
                           ->  Seq Scan on customers c
 Optimizer: GPORCA
```

Тот же JOIN, но заказы распределены по `order_id`. GPORCA перераспределяет заказы по `customer_id`:

```
                     ->  Redistribute Motion 3:3  (slice2; segments: 3)
                           Hash Key: o.customer_id
                           ->  Seq Scan on orders_by_id o
```

Классический планировщик Postgres (`SET optimizer = off`) выбирает другой путь и рассылает
`customers` целиком на каждый сегмент:

```
                     ->  Hash
                           ->  Broadcast Motion 3:3  (slice2; segments: 3)
                                 ->  Seq Scan on customers c
 Optimizer: Postgres query optimizer
```

Точечный запрос по ключу распределения уходит на один сегмент:

```
 Gather Motion 1:1  (slice1; segments: 1)
   ->  Seq Scan on orders_by_id
         Filter: (order_id = 42)
```

В конце оба варианта JOIN дают одинаковый результат:

```
     layout     |  count  |     sum
----------------+---------+-------------
 by customer_id | 1000000 | 49950000.00
 by order_id    | 1000000 | 49950000.00
```

## Шаг 8. Форматы хранения

```bash
psql -X -d postgres -e -v ON_ERROR_STOP=1 -f 04_storage_formats.sql
```

Ожидаемо:

```
  amname
-----------
 ao_column
 ao_row
 heap
 pax

 table_name  | access_method | total_size
-------------+---------------+------------
 orders_heap | heap          | 58 MB
 orders_aoco | ao_column     | 5849 kB
 orders_pax  | pax           | 5717 kB
```

Данные синтетические и сильно повторяются, поэтому сжатие здесь в десять раз. На реальных данных
коэффициент будет другим, неизменна только разница между строчным и колоночным хранением.

## Шаг 9. Остановка и удаление

Остановить кластер, данные остаются:

```bash
gpstop -a
```

Запустить снова: `gpstart -a`. Удалить демо-кластер вместе с каталогом `datadirs` (команда из
документации `gpdemo`, выполняется в каталоге, где кластер создавался):

```bash
cd ~/cloudberry_demo && gpdemo -d
```

## Если не так

- **`psql: command not found` или `gpdemo: command not found`.** Не подключено окружение. В каждой
  новой сессии: `source /usr/local/cloudberry-db/cloudberry-env.sh`, затем в каталоге кластера
  `source gpdemo-env.sh`.
- **`error while loading shared libraries: libprotobuf.so.32` (или `liburing.so.2`,
  `libxerces-c-3.2.so`).** Пакет поставлен через `dpkg -i` без зависимостей. Довести установку:
  `sudo apt-get install -f`.
- **`gpinitsystem` спрашивает пароль или пишет `Permission denied (publickey)`.** Не прошёл шаг 2.
  Проверить вход по ssh и на `localhost`, и на имя из `hostname`: утилиты используют второе.
- **Предупреждения `open file limit is 1024 should be >= 65535`.** Для демо не мешают, кластер
  создаётся. Для нагрузки лимит поднимают в `/etc/security/limits.conf`.
- **В логе `gpdemo` строка `[WARN]:-Failed to start Cloudberry instance`, а в конце
  `gpinitsystem returned: 0`.** На прогоне это была проверка состояния (FTS probe) в момент, когда
  зеркала ещё догоняли primary. Если `gpstate -b` показывает три валидных primary и три зеркала,
  кластер в порядке.
- **Кластер падает после выхода из ssh, в логах сегментов ошибки разделяемой памяти.** Сработал
  `RemoveIPC` logind, см. шаг 3.
- **`port 7000 is already in use`.** Порты заняты другим Postgres или старым кластером. Проверить
  `gpdemo -c` или задать другой диапазон: `PORT_BASE=8000 gpdemo`.
- **В плане нет `Redistribute Motion`, а есть `Broadcast Motion`.** Отключён GPORCA
  (`SHOW optimizer` даёт `off`). Это не ошибка: классический планировщик выбирает рассылку меньшей
  таблицы, шаг 7 показывает оба варианта.
- **У реплицированной таблицы `column "gp_segment_id" does not exist`.** Так и должно быть: у
  `DISTRIBUTED REPLICATED` строка не принадлежит одному сегменту. Номер сегмента берётся функцией
  `gp_execution_segment()` поверх `gp_dist_random()`, как в `02_distribution_skew.sql`.
