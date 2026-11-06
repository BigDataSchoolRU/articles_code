# confluent-kafka 2.16.1, psycopg 3.3.8, Kafka 4.3.2, PostgreSQL 18.6, Debezium 3.7.0.Final, прогнано на стенде 2026-11-06
"""Transactional outbox на PostgreSQL, Kafka и Debezium: сценарии демо.

python outbox_demo.py all|dual_write|polling|duplicate|emit_message|cdc
"""
import base64
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter

import psycopg
from confluent_kafka.admin import AdminClient, NewTopic

from consumer import consume_naive, consume_with_inbox, read_topic
from relay import KAFKA, PG_DSN, RelayCrash, make_producer, relay_batch, run_relay

CONNECT_URL = os.environ.get("CONNECT_URL", "http://127.0.0.1:58083")
HERE = os.path.dirname(os.path.abspath(__file__))


# ── сервис заказов ──────────────────────────────────────────────────────────

def pg():
    return psycopg.connect(PG_DSN, autocommit=True)


def place_order(conn, customer: str, amount: int, fail: bool = False,
                delete_outbox: bool = False) -> int:
    """Заказ и событие OrderCreated одной локальной транзакцией: либо оба, либо ничего."""
    with conn.transaction():
        order_id = conn.execute(
            "INSERT INTO orders (customer, amount) VALUES (%s, %s) RETURNING id",
            (customer, amount)).fetchone()[0]
        payload = {"orderId": order_id, "customer": customer, "amount": amount}
        event_id = conn.execute(
            "INSERT INTO outbox (aggregatetype, aggregateid, type, payload) "
            "VALUES ('order', %s, 'OrderCreated', %s) RETURNING id",
            (str(order_id), json.dumps(payload))).fetchone()[0]
        if delete_outbox:
            # для CDC строка не нужна после коммита: событие уже лежит в WAL
            conn.execute("DELETE FROM outbox WHERE id = %s", (event_id,))
        if fail:
            raise RuntimeError("ошибка бизнес-логики после записи в outbox")
    return order_id


def pay_order(conn, order_id: int, customer: str) -> None:
    with conn.transaction():
        conn.execute("UPDATE orders SET status = 'paid' WHERE id = %s", (order_id,))
        conn.execute(
            "INSERT INTO outbox (aggregatetype, aggregateid, type, payload) "
            "VALUES ('order', %s, 'OrderPaid', %s)",
            (str(order_id), json.dumps({"orderId": order_id, "customer": customer})))


def ensure_topics(*names: str, partitions: int = 3) -> None:
    admin = AdminClient({"bootstrap.servers": KAFKA})
    futures = admin.create_topics([NewTopic(n, partitions, 1) for n in names])
    for name, f in futures.items():
        try:
            f.result(15)
        except Exception as e:  # уже есть: нормально при повторном запуске
            if "TOPIC_ALREADY_EXISTS" not in str(e):
                raise
    time.sleep(1)  # метаданные новых топиков расходятся по клиентам не мгновенно


def count(conn, sql: str, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def order_violations(msgs: list[dict]) -> list[str]:
    """Заказы, у которых OrderPaid лежит в партиции раньше, чем OrderCreated."""
    seen_created, bad = set(), []
    for m in sorted(msgs, key=lambda m: (m["partition"], m["offset"])):
        etype = m["headers"]["eventType"]
        if etype == "OrderCreated":
            seen_created.add(m["key"])
        elif etype == "OrderPaid" and m["key"] not in seen_created:
            bad.append(m["key"])
    return bad


# ── сценарии ────────────────────────────────────────────────────────────────

def dual_write():
    """Двойная запись без outbox: коммит в БД и отправка в Kafka не атомарны."""
    topic = "dualwrite.order"
    ensure_topics(topic)
    producer = make_producer("dual-write")
    with pg() as conn:
        # A. сначала БД, потом брокер: процесс падает между COMMIT и produce
        with conn.transaction():
            a_id = conn.execute("INSERT INTO orders (customer, amount) VALUES ('dw-anna', 1500) "
                                "RETURNING id").fetchone()[0]
        print(f"A: заказ {a_id} закоммичен в БД; процесс упал до produce, событие не отправлено")

        # B. сначала брокер, потом БД: событие ушло, а транзакция откатилась
        b_id = None
        try:
            with conn.transaction():
                b_id = conn.execute("INSERT INTO orders (customer, amount) VALUES ('dw-boris', 2300) "
                                    "RETURNING id").fetchone()[0]
                producer.produce(topic, key=str(b_id), headers=[("eventType", "OrderCreated")],
                                 value=json.dumps({"orderId": b_id, "customer": "dw-boris", "amount": 2300}))
                producer.flush(15)
                print(f"B: событие OrderCreated для заказа {b_id} подтверждено брокером")
                raise ConnectionError("соединение с БД оборвалось до COMMIT")
        except ConnectionError as e:
            print(f"B: {e}, транзакция откатилась")

        msgs = read_topic(topic)
        order_ids_in_topic = {m["value"]["orderId"] for m in msgs}
        a_in_db = count(conn, "SELECT count(*) FROM orders WHERE id = %s", a_id)
        b_in_db = count(conn, "SELECT count(*) FROM orders WHERE id = %s", b_id)
    print(f"итог A: заказ {a_id} в БД: {a_in_db}, событий о нём в топике: {int(a_id in order_ids_in_topic)}"
          f"  -> потерянное событие")
    print(f"итог B: заказ {b_id} в БД: {b_in_db}, событий о нём в топике: {int(b_id in order_ids_in_topic)}"
          f"  -> фантомное событие")


def _fill_outbox(conn, tag: str, n: int, rng: random.Random) -> None:
    """n заказов вперемешку с оплатами: OrderPaid идёт через 0-8 чужих событий после OrderCreated."""
    pending = []  # (момент оплаты, order_id, customer)
    for i in range(n):
        customer = f"{tag}-{i % 17}"
        oid = place_order(conn, customer, 100 * rng.randint(3, 40))
        pending.append((i + rng.randint(0, 8), oid, customer))
        for item in [p for p in pending if p[0] <= i]:
            pay_order(conn, item[1], item[2])
            pending.remove(item)
    for _, oid, customer in pending:
        pay_order(conn, oid, customer)


def _relays(prefix: str, n_relays: int, batch_size: int) -> tuple[list[dict], float]:
    results, threads = [], []
    t0 = time.monotonic()
    for k in range(n_relays):
        th = threading.Thread(target=lambda k=k: results.append(
            run_relay(f"relay-{k + 1}", prefix, batch_size)))
        threads.append(th)
        th.start()
    for th in threads:
        th.join()
    return sorted(results, key=lambda r: r["relay"]), time.monotonic() - t0


def polling():
    """Polling publisher: заказ и событие одной транзакцией, два ретранслятора через SKIP LOCKED."""
    rng = random.Random(42)
    n = 100
    with pg() as conn:
        # откат: ни заказа, ни события
        try:
            place_order(conn, "poll-rollback", 999, fail=True)
        except RuntimeError as e:
            print(f"откат: {e}")
        print("после отката: заказов", count(conn, "SELECT count(*) FROM orders WHERE customer = 'poll-rollback'"),
              "строк outbox", count(conn, "SELECT count(*) FROM outbox WHERE payload->>'customer' = 'poll-rollback'"))

        for variant, n_relays in (("one", 1), ("two", 2)):
            prefix = f"polling_{variant}.event"
            topic = f"{prefix}.order"
            ensure_topics(topic)
            _fill_outbox(conn, f"poll-{variant}", n, rng)
            pending = count(conn, "SELECT count(*) FROM outbox WHERE published_at IS NULL")
            stats, took = _relays(prefix, n_relays, batch_size=10)
            msgs = read_topic(topic)
            ids = Counter(m["headers"]["id"] for m in msgs)
            left = count(conn, "SELECT count(*) FROM outbox WHERE published_at IS NULL")
            print(f"\n[{n_relays} ретранслятор(а)] в outbox к отправке: {pending} событий ({n} заказов x 2)")
            for s in stats:
                print(f"  {s['relay']}: пачек {s['batches']}, событий {s['events']}")
            print(f"  в топике {topic}: сообщений {len(msgs)}, уникальных id {len(ids)}, "
                  f"повторов {sum(v - 1 for v in ids.values())}")
            print(f"  неотправленных строк в outbox: {left}; ушло за {took:.2f} с "
                  f"(включая {1.0:.1f} с ожидания пустой таблицы)")
            bad = order_violations(msgs)
            print(f"  заказов, у которых OrderPaid в партиции раньше OrderCreated: {len(bad)} из {n}")
            if bad:
                trail = [f"{m['headers']['eventType']}@p{m['partition']}:{m['offset']}"
                         for m in sorted(msgs, key=lambda m: m["offset"]) if m["key"] == bad[0]]
                print(f"  пример, заказ {bad[0]}: {' -> '.join(trail)}")

        _paused_relay(conn)


def _paused_relay(conn) -> None:
    """Детерминированно: первый ретранслятор держит пачку с OrderCreated, второй отправляет OrderPaid."""
    prefix = "polling_pause.event"
    topic = f"{prefix}.order"
    ensure_topics(topic)
    oid = place_order(conn, "poll-pause", 1500)
    pay_order(conn, oid, "poll-pause")
    locked, second_done = threading.Event(), threading.Event()

    def hold(rows):
        print(f"  relay-1 захватил {[r[3] for r in rows]} и замер до отправки")
        locked.set()
        second_done.wait(15)

    def first():
        with pg() as c1:
            relay_batch(c1, make_producer("relay-1"), prefix, batch_size=1, before_produce=hold)

    th = threading.Thread(target=first)
    th.start()
    locked.wait(15)
    with pg() as c2:
        # SKIP LOCKED пропускает строку relay-1 и отдаёт следующую: OrderPaid того же заказа
        relay_batch(c2, make_producer("relay-2"), prefix, batch_size=1,
                    before_produce=lambda rows: print(f"  relay-2 захватил {[r[3] for r in rows]}, строку relay-1 пропустил"))
    second_done.set()
    th.join()
    msgs = sorted(read_topic(topic), key=lambda m: m["offset"])
    trail = [f"{m['headers']['eventType']}@p{m['partition']}:{m['offset']}" for m in msgs]
    print(f"\n[2 ретранслятора, relay-1 замер] заказ {oid}: {' -> '.join(trail)}")


def duplicate():
    """Ретранслятор падает после отправки и до отметки: повтор, который гасит inbox."""
    prefix, topic = "dup.event", "dup.event.order"
    ensure_topics(topic)
    amounts = [1200, 800, 4500, 300, 2100]
    expected = sum(a // 100 for a in amounts)
    with pg() as conn:
        conn.execute("TRUNCATE loyalty.points, loyalty.inbox")
        for i, a in enumerate(amounts):
            place_order(conn, f"dup-{i}", a)
        try:
            with pg() as relay_conn:
                relay_batch(relay_conn, make_producer("relay-crash"), prefix, batch_size=10,
                            crash_after_produce=True)
        except RelayCrash as e:
            print(f"1-й запуск ретранслятора: {e}")
        print("  сообщений в топике:", len(read_topic(topic)),
              "| неотправленных строк в outbox:", count(conn, "SELECT count(*) FROM outbox WHERE published_at IS NULL"))
        print("2-й запуск ретранслятора:", run_relay("relay-restart", prefix))
        msgs = read_topic(topic)
        ids = Counter(m["headers"]["id"] for m in msgs)
        print(f"  сообщений в топике: {len(msgs)}, уникальных id: {len(ids)}")

        print(f"\nожидаемые баллы: {expected}")
        print("наивный консьюмер:", consume_naive(topic, "loyalty-naive"),
              "| баллов начислено:", count(conn, "SELECT coalesce(sum(points), 0) FROM loyalty.points"))
        conn.execute("TRUNCATE loyalty.points, loyalty.inbox")
        print("inbox, 1-й проход (падает до коммита оффсетов):",
              consume_with_inbox(topic, "loyalty-inbox", crash_before_offset_commit=True))
        print("inbox, 2-й проход после рестарта:", consume_with_inbox(topic, "loyalty-inbox"))
        print("inbox, 3-й проход:", consume_with_inbox(topic, "loyalty-inbox"))
        print("  баллов начислено:", count(conn, "SELECT coalesce(sum(points), 0) FROM loyalty.points"),
              "| строк в inbox:", count(conn, "SELECT count(*) FROM loyalty.inbox"))


def emit_message():
    """pg_logical_emit_message: событие прямо в WAL, без строки в таблице outbox."""
    with pg() as conn:
        outbox_before = count(conn, "SELECT count(*) FROM outbox")
        conn.execute("SELECT pg_create_logical_replication_slot('emit_demo', 'test_decoding')")
        with conn.transaction():
            oid = conn.execute("INSERT INTO orders (customer, amount) VALUES ('emit-1', 700) "
                               "RETURNING id").fetchone()[0]
            conn.execute("SELECT pg_logical_emit_message(true, 'outbox', %s)",
                         (json.dumps({"type": "OrderCreated", "orderId": oid}),))
        for transactional in (True, False):
            try:
                with conn.transaction():
                    # flush=true сбрасывает нетранзакционное сообщение в WAL сразу: без него оно ждёт
                    # в буферах, а pg_logical_slot_get_changes читает только сброшенное на диск
                    conn.execute("SELECT pg_logical_emit_message(%s, 'outbox', %s, true)",
                                 (transactional, json.dumps({"type": "OrderCreated",
                                                             "note": f"rollback, transactional={transactional}"})))
                    raise RuntimeError("откат")
            except RuntimeError:
                pass
        rows = conn.execute("SELECT lsn, xid, data FROM pg_logical_slot_get_changes('emit_demo', NULL, NULL) "
                            "WHERE data LIKE 'message%%' OR data LIKE 'table public.orders%%'").fetchall()
        for lsn, xid, data in rows:
            print(f"  {lsn} xid={xid} {data}")
        conn.execute("SELECT pg_drop_replication_slot('emit_demo')")
        print("строк в outbox до и после:", outbox_before, count(conn, "SELECT count(*) FROM outbox"))


def _connect(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(CONNECT_URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


def _wait_for(topic: str, n: int, timeout: float = 60.0) -> list[dict]:
    deadline = time.monotonic() + timeout
    while True:
        msgs = read_topic(topic, timeout=5)
        if len(msgs) >= n or time.monotonic() > deadline:
            return msgs
        time.sleep(0.3)


def cdc():
    """Тот же outbox через Debezium: WAL -> PostgreSQL connector -> Outbox Event Router -> топик."""
    topic, msg_topic = "outbox.event.order", "shop.message"
    ensure_topics(topic, msg_topic)
    cfg = json.load(open(os.path.join(HERE, "connector.json"), encoding="utf-8"))
    _connect("PUT", f"/connectors/{cfg['name']}/config", cfg["config"])
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            st = _connect("GET", f"/connectors/{cfg['name']}/status")
            if st["connector"]["state"] == "RUNNING" and st["tasks"] and \
                    all(t["state"] == "RUNNING" for t in st["tasks"]):
                break
        except Exception:
            pass
        time.sleep(1)
    print("коннектор:", st["connector"]["state"], "задачи:", [t["state"] for t in st["tasks"]])
    with pg() as conn:
        # слот должен стать активным, иначе первые вставки уйдут в WAL раньше, чем коннектор начнёт читать
        for _ in range(60):
            if count(conn, "SELECT count(*) FROM pg_replication_slots WHERE slot_name = 'outbox_slot' AND active"):
                break
            time.sleep(1)
        print("слот:", conn.execute("SELECT slot_name, plugin, active FROM pg_replication_slots "
                                    "WHERE slot_name = 'outbox_slot'").fetchone())
        t_commit = time.monotonic()
        ids = [place_order(conn, f"cdc-{i}", a) for i, a in enumerate((1100, 2600, 900))]
        ids += [place_order(conn, f"cdc-del-{i}", a, delete_outbox=True) for i, a in enumerate((1700, 500))]
        try:
            place_order(conn, "cdc-rollback", 999, fail=True)
        except RuntimeError:
            pass
        msgs = _wait_for(topic, len(ids))
        print(f"5 коммитов -> {len(msgs)} сообщений в {topic} за {time.monotonic() - t_commit:.2f} с")
        for m in sorted(msgs, key=lambda m: int(m["key"])):
            print(f"  p{m['partition']} key={m['key']} eventType={m['headers'].get('eventType')} "
                  f"id={m['headers'].get('id')} value={json.dumps(m['value'], ensure_ascii=False)}")
        print("строк outbox у заказов cdc-del-*:",
              count(conn, "SELECT count(*) FROM outbox WHERE payload->>'customer' LIKE 'cdc-del-%%'"),
              "| событий cdc-rollback в топике:",
              sum(1 for m in msgs if m["value"]["customer"] == "cdc-rollback"))

        # UPDATE строки outbox: SMT не превращает его в событие, а пишет предупреждение в лог
        conn.execute("UPDATE outbox SET payload = payload || '{\"amount\": 1}' "
                     "WHERE payload->>'customer' = 'cdc-0'")
        time.sleep(5)
        print("после UPDATE строки outbox сообщений в топике:", len(read_topic(topic)))
        try:
            log = subprocess.run(["docker", "logs", "outbox-connect"], capture_output=True, text=True,
                                 timeout=30)
            lines = [ln for ln in (log.stdout + log.stderr).splitlines()
                     if "WARN" in ln and "EventRouter" in ln]
            for ln in lines[-2:]:
                print("  лог Connect:", ln[:400])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("  docker logs недоступен, смотрите лог контейнера outbox-connect вручную")

        # логическое сообщение в той же транзакции, что и заказ: Debezium пишет его в <topic.prefix>.message
        with conn.transaction():
            oid = conn.execute("INSERT INTO orders (customer, amount) VALUES ('cdc-msg', 3100) "
                               "RETURNING id").fetchone()[0]
            conn.execute("SELECT pg_logical_emit_message(true, 'outbox', %s)",
                         (json.dumps({"type": "OrderCreated", "orderId": oid}),))
        try:  # нетранзакционное сообщение в откатившейся транзакции: дойдёт ли оно до Debezium
            with conn.transaction():
                conn.execute("SELECT pg_logical_emit_message(false, 'outbox', %s, true)",
                             (json.dumps({"type": "OrderCreated", "note": "rollback, transactional=false"}),))
                raise RuntimeError("откат")
        except RuntimeError:
            pass
        mm = _wait_for(msg_topic, 2, timeout=30)
        print(f"сообщений в {msg_topic}: {len(mm)}")
        for m in mm:
            msg = m["value"]["message"]
            print(f"  op={m['value']['op']} txId={m['value']['source']['txId']} prefix={msg['prefix']} "
                  f"content={base64.b64decode(msg['content']).decode()}")
        if mm:
            print("  value целиком:", json.dumps(mm[0]["value"], ensure_ascii=False)[:700])

    print("\ninbox-консьюмер на топике Debezium:", consume_with_inbox(topic, "loyalty-cdc"))


SCENARIOS = {"dual_write": dual_write, "polling": polling, "duplicate": duplicate,
             "emit_message": emit_message, "cdc": cdc}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "all"
    for key, fn in SCENARIOS.items():
        if name in ("all", key):
            print(f"\n=== {key} ===")
            t0 = time.monotonic()
            fn()
            print(f"--- {key}: {time.monotonic() - t0:.1f} с")
