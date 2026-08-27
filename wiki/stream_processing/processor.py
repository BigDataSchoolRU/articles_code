# confluent-kafka 2.15.0, Kafka 4.3.0 (образ apache/kafka, стенд event_streaming),
# прогнано на стенде 2026-08-27
"""
Минимальный процессор потока с нуля (не обёртка вокруг Kafka Streams/Flink):
считает tumbling-агрегат (среднее по датчику) по event time, закрывает окно
только после прохождения watermark, периодически сбрасывает состояние в файл
и восстанавливается из него после "падения".

Механизм:
  - watermark = максимальный увиденный event_time минус допустимое опоздание
    (LATENESS_SEC). Событие с окном, чей конец уже <= watermark, считается
    опоздавшим и не учитывается в агрегате.
  - Окно закрывается (агрегат печатается и убирается из состояния), когда
    watermark проходит его конец. Однопартиционный топик даёт один глобальный
    watermark — с несколькими партициями в реальных системах берётся минимум
    watermark по всем партициям источника.
  - Чекпоинт (offset, состояние окон, watermark, счётчик опоздавших) пишется
    в JSON атомарно (tmp-файл + os.replace) после каждого сообщения. При
    старте, если чекпоинт есть, процессор восстанавливает состояние и
    продолжает читать топик с сохранённого offset+1, не пересчитывая уже
    закрытые окна заново.
  - Флаг --crash-after имитирует падение процесса после N обработанных
    сообщений С НАЧАЛА ВСЕГО ПРОГОНА (детерминированно, для воспроизводимой
    демонстрации восстановления вместо реального kill -9 в терминале).
  - Конец потока в этом демо определяется фиксированным числом событий
    (--expected-count), а не таймаутом простоя: источник конечен и заранее
    известен. В боевой системе конец обычно не наступает, и "закрытие всех
    окон" делается сдвигом watermark на +бесконечность при штатной остановке
    источника, а не по счётчику.
"""
import argparse
import json
import os
import sys

from confluent_kafka import Consumer, TopicPartition

TOPIC = "stream_processing_events"
BOOTSTRAP = "localhost:9092"
CHECKPOINT_PATH = "checkpoint.json"

WINDOW_SIZE_SEC = 10
LATENESS_SEC = 5


def load_checkpoint():
    if not os.path.exists(CHECKPOINT_PATH):
        return None
    with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(offset, state, watermark, emitted, late_dropped, processed_count):
    data = {
        "offset": offset,
        "state": state,
        "watermark": watermark,
        "emitted": sorted(emitted),
        "late_dropped": late_dropped,
        "processed_count": processed_count,
    }
    tmp_path = CHECKPOINT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, CHECKPOINT_PATH)


def close_windows(state, watermark, emitted):
    """Закрывает окна, чей конец уже пройден watermark. Возвращает число закрытых."""
    closed = 0
    for key in sorted(state.keys(), key=lambda k: (int(k.split("|")[1]), k.split("|")[0])):
        sensor_id, window_start_str = key.split("|")
        window_start = int(window_start_str)
        window_end = window_start + WINDOW_SIZE_SEC
        if window_end <= watermark and key not in emitted:
            agg = state.pop(key)
            avg = agg["sum"] / agg["count"]
            emitted.add(key)
            closed += 1
            print(f"[emit] sensor={sensor_id} window=[{window_start},{window_end}) "
                  f"count={agg['count']} avg={avg:.2f} watermark={watermark}")
    return closed


def process_event(payload, state, watermark, emitted):
    """Возвращает (новый watermark, опоздало ли событие)."""
    sensor_id = payload["sensor_id"]
    event_time = payload["event_time"]
    value = payload["value"]
    window_start = (event_time // WINDOW_SIZE_SEC) * WINDOW_SIZE_SEC
    window_end = window_start + WINDOW_SIZE_SEC
    key = f"{sensor_id}|{window_start}"

    if window_end <= watermark or key in emitted:
        print(f"[late-drop] sensor={sensor_id} event_time={event_time} value={value} "
              f"window=[{window_start},{window_end}) уже закрыто при watermark={watermark}")
        return watermark, True

    agg = state.setdefault(key, {"sum": 0.0, "count": 0})
    agg["sum"] += value
    agg["count"] += 1

    if event_time - LATENESS_SEC > watermark:
        watermark = event_time - LATENESS_SEC
        close_windows(state, watermark, emitted)

    return watermark, False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crash-after", type=int, default=None,
                         help="имитировать падение после N сообщений с начала всего прогона")
    parser.add_argument("--expected-count", type=int, default=14,
                         help="сколько всего событий в демо-потоке")
    args = parser.parse_args()

    checkpoint = load_checkpoint()
    if checkpoint is not None:
        state = checkpoint["state"]
        watermark = checkpoint["watermark"]
        emitted = set(checkpoint["emitted"])
        late_dropped = checkpoint["late_dropped"]
        processed_count = checkpoint["processed_count"]
        resume_offset = checkpoint["offset"] + 1
        print(f"восстановление из чекпоинта: offset={resume_offset}, "
              f"watermark={watermark}, обработано ранее={processed_count}")
    else:
        state, watermark, emitted = {}, -1_000_000, set()
        late_dropped, processed_count = 0, 0
        resume_offset = 0
        print("чекпоинта нет, старт с начала топика")

    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": "stream-processing-demo",
        "enable.auto.commit": False,
    })
    consumer.assign([TopicPartition(TOPIC, 0, resume_offset)])

    last_offset = resume_offset - 1
    idle_polls = 0
    try:
        while processed_count < args.expected_count:
            msg = consumer.poll(1.0)
            if msg is None:
                idle_polls += 1
                if idle_polls > 15:
                    print("простой топика дольше ожидаемого, останавливаюсь", file=sys.stderr)
                    break
                continue
            idle_polls = 0
            if msg.error():
                print(f"ошибка consumer: {msg.error()}", file=sys.stderr)
                continue

            payload = json.loads(msg.value().decode("utf-8"))
            watermark, was_late = process_event(payload, state, watermark, emitted)
            if was_late:
                late_dropped += 1
            last_offset = msg.offset()
            processed_count += 1
            save_checkpoint(last_offset, state, watermark, emitted, late_dropped, processed_count)

            if args.crash_after is not None and processed_count >= args.crash_after:
                print(f"имитация падения после {processed_count} сообщений "
                      f"(чекпоинт уже на диске на offset={last_offset})")
                sys.exit(1)

        if processed_count >= args.expected_count:
            # конец потока: сдвигаем watermark на +бесконечность и закрываем всё, что осталось
            print("конец потока, финальный флаш оставшихся окон")
            close_windows(state, float("inf"), emitted)
            save_checkpoint(last_offset, state, float("inf"), emitted, late_dropped, processed_count)

        print(f"итого: обработано={processed_count}, опоздавших и отброшенных={late_dropped}, "
              f"окон закрыто={len(emitted)}, окон осталось открытыми={len(state)}")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
