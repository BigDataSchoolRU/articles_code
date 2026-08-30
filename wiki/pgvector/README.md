# pgvector

Код к статье [pgvector](https://bigdataschool.ru/wiki/pgvector/) на Wiki BigDataSchool.

## Файлы

- `setup.sql` — расширение `vector`, таблица с векторной колонкой, 5000 тестовых строк.
- `hnsw_index.sql` — построение индекса HNSW для косинусного расстояния.
- `ann_query.sql` — обычный ANN-запрос оператором `<=>`.
- `hybrid_query.sql` — гибридный запрос с фильтром `WHERE` и демонстрация overfiltering
  (`hnsw.iterative_scan`).
- `RUNBOOK.md` — пошаговый прогон демо с нуля, включая типовые ошибки.

## Окружение

PostgreSQL 14+ (демо прогонялось на 18.4) с установленным расширением `pgvector` 0.8.0+
(демо прогонялось на 0.8.6). Внешние сервисы не нужны — весь векторный поиск идёт внутри
самого PostgreSQL.

## Как запустить

```bash
createdb pgvector_demo
psql -d pgvector_demo -f setup.sql
psql -d pgvector_demo -f hnsw_index.sql
psql -d pgvector_demo -f ann_query.sql
psql -d pgvector_demo -f hybrid_query.sql
```

Подробности и разбор возможных ошибок — в `RUNBOOK.md`.
