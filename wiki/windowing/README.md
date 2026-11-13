# Windowing: tumbling, sliding и session окна в Spark Structured Streaming

Код к Wiki-статье «Windowing»: https://bigdataschool.ru/wiki/windowing/

Один и тот же поток из 17 событий двух пользователей проходит через три типа окон: tumbling
(10 минут), sliding (10 минут с шагом 5) и session (пауза 5 минут). Watermark 5 минут, режим
вывода append: окно попадает в результат один раз, когда watermark прошёл его конец. Скрипт
печатает закрытые окна, размер состояния после каждого микробатча, отброшенное опоздавшее
событие и показывает, что в sliding-окнах каждое событие учитывается дважды.

## Файлы

| Файл | Что делает |
|---|---|
| `events.jsonl` | 17 событий (`id`, `user`, `ts`), поле `batch` задаёт, в какой из пяти микробатчей придёт событие; `e15` опаздывает намеренно. Прогнано на Apache Spark 4.0.4, 2026-11-13 |
| `windows_demo.py` | раскладывает события по файлам, считает окна на событие на статическом DataFrame, затем гоняет три потоковых запроса с `window`, `window` со сдвигом и `session_window` |
| `compose.yaml` | Spark 4.0.4 в образе `apache/spark` и `spark-submit` скрипта, папка проекта только на чтение |
| `log4j2.properties` | оставляет в консоли Spark только ошибки |
| `RUNBOOK.md` | пошаговый запуск с ожидаемым выводом |

## Окружение

Docker с Compose v2, около 3 ГБ свободной памяти и 2.1 ГБ диска под образ
`apache/spark:4.0.4-scala2.13-java17-python3-ubuntu`. Python и Java на хосте не нужны: PySpark
4.0.4 и Python 3.10 лежат в образе.

## Как запустить

```bash
docker pull apache/spark:4.0.4-scala2.13-java17-python3-ubuntu
docker compose run --rm spark
```

Холодный запуск около минуты. Подробности и ожидаемый вывод в `RUNBOOK.md`.
