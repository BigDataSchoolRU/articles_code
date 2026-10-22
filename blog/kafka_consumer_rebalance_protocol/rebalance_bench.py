# confluent-kafka 2.16.0, Apache Kafka 4.3.2, прогнано на стенде 2026-10-22
"""Замер паузы в чтении при ребалансировке: eager, cooperative-sticky, static и consumer (KIP-848).

consumer_hb1s это тот же KIP-848, но группе выставлен consumer.heartbeat.interval.ms=1000
вместо брокерных 5000 мс по умолчанию.

Группа из 4 потребителей читает топик на 12 партиций под ровной нагрузкой 1200 сообщений/с.
По очереди происходят четыре события:
  add     - пятый участник входит в группу;
  leave   - он же выходит мягко, через close();
  crash   - участник убит SIGKILL и больше не возвращается;
  restart - участник убит и через секунду запущен заново под тем же именем.
Пауза партиции это максимальная задержка «прочитано минус записано» новых сообщений
в окне события. Остановленной считается партиция с паузой больше 1 с.

Запуск: python rebalance_bench.py [повторов, по умолчанию 3]
"""

import json
import statistics
import sys
import threading
import time

import producer_load
from group_member import GROUP_CONFIGS, MODES, Group, set_group_config

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
# Минимальная длина окна события: тайм-аут сессии 10 с плюс запас на ребалансировку
WINDOW = {"add": 12, "leave": 12, "crash": 20, "restart": 20}
FIELDS = ["stalled", "max_pause", "stall_sum", "revoked", "revokers", "dup", "cb_span"]


def measure(g: Group, event: str, action) -> dict:
    t0 = time.time()
    action()
    time.sleep(WINDOW[event])
    g.wait_stable(60)
    time.sleep(2)  # даём дочитать задержанные сообщения
    res = g.window(t0, time.time())
    res["took"] = round(time.time() - t0, 1)
    return res


def one_run(mode: str, run: int) -> dict:
    g = Group(f"bench-{mode}-{run}-{int(time.time())}")
    if mode in GROUP_CONFIGS:
        set_group_config(g.group, GROUP_CONFIGS[mode])
    for i in range(1, 5):
        g.start(mode, f"m{i}")
    warm = g.wait_stable(90)
    time.sleep(3)
    g.window(0, time.time())  # прогрев не считаем, только запоминаем offsets
    out = {"warmup": round(warm, 1)}

    def restart():
        g.kill("m3")
        time.sleep(1)
        g.start(mode, "m3")

    out["add"] = measure(g, "add", lambda: g.start(mode, "m5"))
    out["leave"] = measure(g, "leave", lambda: g.leave("m5"))
    out["crash"] = measure(g, "crash", lambda: g.kill("m4"))
    out["restart"] = measure(g, "restart", restart)
    g.stop_all()
    return out


def main() -> None:
    stop = threading.Event()
    threading.Thread(target=producer_load.run, args=(stop,), daemon=True).start()
    time.sleep(3)
    results = {m: [] for m in MODES}
    for mode in MODES:
        for run in range(1, REPEATS + 1):
            r = one_run(mode, run)
            results[mode].append(r)
            print(f"\n[{mode} #{run}] прогрев до стабильной группы {r['warmup']} с", flush=True)
            for ev in WINDOW:
                e = r[ev]
                print(f"  {ev:8} остановлено {e['stalled']:2}/12, макс. пауза {e['max_pause']:6.2f} с, "
                      f"сумма {e['stall_sum']:6.1f} парт.·с, отозвано {e['revoked']:2} у {e['revokers']} "
                      f"участн., повторов {e['dup']}, колбэки за {e['cb_span']} с", flush=True)
    stop.set()

    print("\n=== МЕДИАНЫ ПО", REPEATS, "ПОВТОРАМ ===")
    print(f"{'вариант':14}{'событие':9}{'останов.':>9}{'макс.пауза,с':>14}{'сумма,парт.·с':>15}"
          f"{'отозвано':>10}{'повторов':>10}")
    summary = {}
    for mode, runs in results.items():
        for ev in WINDOW:
            med = {f: statistics.median(r[ev][f] for r in runs) for f in FIELDS}
            summary[f"{mode}/{ev}"] = med
            print(f"{mode:14}{ev:9}{med['stalled']:>9}{med['max_pause']:>14.2f}{med['stall_sum']:>15.1f}"
                  f"{med['revoked']:>10}{med['dup']:>10}")
    with open("bench_results.json", "w", encoding="utf-8") as f:
        json.dump({"runs": results, "median": summary}, f, ensure_ascii=False, indent=1)
    print("сырые данные: bench_results.json")


if __name__ == "__main__":
    main()
