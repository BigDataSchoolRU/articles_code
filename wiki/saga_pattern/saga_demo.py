# psycopg 3.3.8, postgres 18.6, прогнано на стенде 2026-11-12
"""Сценарии оркестрированной саги заказа на PostgreSQL.

    python saga_demo.py all             # happy, compensate, retry, crash, isolation
    python saga_demo.py happy|compensate|retry|crash|isolation
    python saga_demo.py two_pc          # двухфазный коммит: координатор падает после PREPARE
    python saga_demo.py two_pc_recover  # после рестарта сервера: подготовленные транзакции на месте

Каждый сценарий начинает с чистых данных (reset), поэтому их можно гонять в любом порядке.
"""
import subprocess
import sys
import threading
import time

import psycopg
from psycopg import sql

import services as s
from orchestrator import Orchestrator, recover

KETTLE = {"sku": "kettle", "price": 250}


def order(customer, qty=1):
    return {"customer": customer, "sku": KETTLE["sku"], "qty": qty, "amount": KETTLE["price"] * qty}


def rollback_prepared(conn):
    # висящие подготовленные транзакции от two_pc держат блокировки, TRUNCATE на них встанет
    for (gid,) in conn.execute(
        "SELECT gid FROM pg_prepared_xacts WHERE database = current_database()"
    ).fetchall():
        conn.execute(sql.SQL("ROLLBACK PREPARED {}").format(sql.Literal(gid)))


def reset(stock=10):
    with psycopg.connect(f"{s.DSN} dbname=inventory", autocommit=True) as conn:
        rollback_prepared(conn)
        conn.execute("TRUNCATE reservations, stock")
        conn.execute("INSERT INTO stock VALUES (%s, %s)", (KETTLE["sku"], stock))
    with psycopg.connect(f"{s.DSN} dbname=payments", autocommit=True) as conn:
        rollback_prepared(conn)
        conn.execute("TRUNCATE payments, accounts")
        conn.execute("INSERT INTO accounts VALUES ('alice', 1000), ('bob', 100)")
    with s.connect("orders") as conn:
        conn.execute("TRUNCATE orders")
    with s.connect("saga") as conn:
        conn.execute("TRUNCATE saga_log, saga_instances")


def table(db, query, title):
    with s.connect(db) as conn:
        cur = conn.execute(query)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    print(f"  -- {db}: {title}")
    widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c))
              for i, c in enumerate(cols)]
    print("     " + " | ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    for r in rows:
        print("     " + " | ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    if not rows:
        print("     (пусто)")


def state(log=True):
    table("orders", "SELECT order_id, customer, qty, amount, status FROM orders ORDER BY 1", "заказы")
    table("inventory", "SELECT sku, available FROM stock", "остаток")
    table("inventory", "SELECT idem_key, qty, status FROM reservations ORDER BY updated_at, idem_key",
          "резервы")
    table("payments", "SELECT customer, balance FROM accounts ORDER BY 1", "счета")
    table("payments", "SELECT idem_key, amount, status FROM payments ORDER BY 1", "платежи")
    table("saga", "SELECT saga_id, state FROM saga_instances ORDER BY 1", "саги")
    if log:
        table("saga", "SELECT saga_id, step, action, status FROM saga_log ORDER BY id", "журнал")


def head(title):
    print(f"\n=== {title} ===", flush=True)


# ── 1. Успешная сага ────────────────────────────────────────────────────────
def happy():
    head("happy: alice покупает 2 чайника, все шаги проходят")
    reset()
    print("  итог:", Orchestrator().start("S-happy", order("alice", 2)))
    state()


# ── 2. Отказ на pivot-шаге и компенсации ────────────────────────────────────
def compensate():
    head("compensate: у bob 100 на счёте, заказ на 500, оплата отклонена")
    reset()
    print("  итог:", Orchestrator().start("S-comp", order("bob", 2)))
    state()


# ── 3. Временный сбой после pivot: повтор вперёд, а не компенсация ──────────
def retry():
    head("retry: деньги списаны, confirm_order дважды не отвечает")
    reset()
    orch = Orchestrator(faults={"confirm_order": 2})
    print("  итог:", orch.start("S-retry", order("alice", 1)))
    state(log=True)


# ── 4. Падение оркестратора между коммитом шага и записью в журнал ──────────
def crash_once(idempotent):
    mode = "idem" if idempotent else "naive"
    saga_id = f"S-crash-{mode}"
    reset()
    print(f"  -- запуск оркестратора в отдельном процессе, ключ шага: "
          f"{'saga_id:step' if idempotent else 'новый uuid на каждую попытку'}", flush=True)
    rc = subprocess.run([sys.executable, __file__, "_crash_worker", saga_id, mode]).returncode
    print(f"  процесс оркестратора завершился с кодом {rc}")
    print("  -- состояние после падения")
    state()
    print("  -- рестарт оркестратора", flush=True)
    print("  итог:", recover(Orchestrator(idempotent=idempotent)))
    print("  -- состояние после восстановления")
    state()


def crash():
    head("crash, вариант 1: ключ идемпотентности saga_id:step")
    crash_once(True)
    head("crash, вариант 2: без стабильного ключа (контрольный прогон)")
    crash_once(False)


def crash_worker(saga_id, mode):
    Orchestrator(idempotent=(mode == "idem"), crash_after="reserve_stock").start(
        saga_id, order("alice", 2))


# ── 5. Нет изоляции между сагами: грязное чтение и semantic lock ────────────
def isolation_once(semantic_lock):
    reset(stock=1)
    t0 = time.monotonic()
    a_reserved, a_go = threading.Event(), threading.Event()

    def pause_a(_):
        a_reserved.set()
        a_go.wait(10)

    result = {}
    # Сага A: bob, денег не хватит. Резервирует последний чайник и встаёт перед оплатой
    a = Orchestrator(hooks={"after:reserve_stock": pause_a}, t0=t0)
    ta = threading.Thread(target=lambda: result.update(A=a.start("S-A-bob", order("bob"))))
    ta.start()
    a_reserved.wait(10)
    print(f"  -- A зарезервировала последний чайник и ждёт; стартует B "
          f"(semantic_lock={semantic_lock})", flush=True)
    # Сага B: alice, денег хватает. Видит промежуточное состояние саги A
    b = Orchestrator(semantic_lock=semantic_lock, backoff=0.3, t0=t0,
                     hooks={"retry:reserve_stock": lambda _: a_go.set()})
    tb = threading.Thread(target=lambda: result.update(B=b.start("S-B-alice", order("alice"))))
    tb.start()
    if not semantic_lock:
        tb.join()
        print("  -- B закончилась, A продолжает", flush=True)
        a_go.set()
    ta.join()
    tb.join()
    print("  итог:", result)
    state()


def isolation():
    head("isolation, вариант 1: склад отвечает «нет товара» на резерв чужой саги")
    isolation_once(False)
    head("isolation, вариант 2: semantic lock, резерв PENDING значит «занято, повтори»")
    isolation_once(True)


# ── 6. Двухфазный коммит для сравнения ──────────────────────────────────────
GIDS = {"inventory": "order-T1-inventory", "payments": "order-T1-payments"}


def two_pc():
    head("two_pc: координатор готовит транзакцию в двух базах и падает до COMMIT PREPARED")
    reset()
    work = {
        "inventory": "UPDATE stock SET available = available - 1 WHERE sku = 'kettle'",
        "payments": "UPDATE accounts SET balance = balance - 250 WHERE customer = 'alice'",
    }
    for db, stmt in work.items():
        with psycopg.connect(f"{s.DSN} dbname={db}", autocommit=True) as conn:
            conn.execute("BEGIN")
            conn.execute(stmt)
            conn.execute(sql.SQL("PREPARE TRANSACTION {}").format(sql.Literal(GIDS[db])))
            print(f"  {db}: PREPARE TRANSACTION '{GIDS[db]}' -> участник проголосовал «готов»")
    print("  координатор упал: COMMIT PREPARED не отправлен, соединения закрыты", flush=True)
    show_prepared()
    blocked_update()


def show_prepared():
    with psycopg.connect(f"{s.DSN} dbname=inventory", autocommit=True) as conn:
        rows = conn.execute(
            "SELECT gid, database, to_char(prepared, 'HH24:MI:SS') FROM pg_prepared_xacts ORDER BY gid"
        ).fetchall()
    print(f"  -- pg_prepared_xacts: {len(rows)}")
    for r in rows:
        print("     ", " | ".join(r))
    print("  -- pg_locks без процесса-владельца (pid IS NULL), их держат подготовленные транзакции:")
    for db in GIDS:
        with psycopg.connect(f"{s.DSN} dbname={db}", autocommit=True) as conn:
            locks = conn.execute(
                """SELECT l.virtualtransaction, l.locktype,
                          coalesce(l.relation::regclass::text, l.transactionid::text), l.mode
                   FROM pg_locks l
                   WHERE l.pid IS NULL
                     AND (l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
                          OR (l.locktype = 'transactionid' AND l.transactionid =
                              (SELECT transaction FROM pg_prepared_xacts WHERE gid = %s)))
                   ORDER BY 2, 3""",
                (GIDS[db],),
            ).fetchall()
        for r in locks:
            print(f"      {db:<9} | " + " | ".join(r))


def blocked_update():
    with psycopg.connect(f"{s.DSN} dbname=inventory", autocommit=True) as conn:
        print("  -- чтение не блокируется, но видит старое значение:",
              conn.execute("SELECT available FROM stock WHERE sku = 'kettle'").fetchone()[0])
        conn.execute("SET lock_timeout = '3s'")
        t = time.monotonic()
        try:
            conn.execute("UPDATE stock SET available = available - 1 WHERE sku = 'kettle'")
            print("  -- запись прошла (неожиданно)")
        except psycopg.errors.LockNotAvailable as e:
            print(f"  -- запись в ту же строку ждала {time.monotonic() - t:.1f} с и упала: "
                  f"{type(e).__name__}: {str(e).splitlines()[0]}")


def two_pc_recover():
    head("two_pc_recover: сервер перезапущен, координатор поднялся и дочитывает свой журнал")
    show_prepared()
    blocked_update()
    for db, gid in GIDS.items():
        with psycopg.connect(f"{s.DSN} dbname={db}", autocommit=True) as conn:
            conn.execute(sql.SQL("COMMIT PREPARED {}").format(sql.Literal(gid)))
            print(f"  {db}: COMMIT PREPARED '{gid}'")
    show_prepared()
    state(log=False)


SCENARIOS = {"happy": happy, "compensate": compensate, "retry": retry, "crash": crash,
             "isolation": isolation, "two_pc": two_pc, "two_pc_recover": two_pc_recover}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "_crash_worker":
        crash_worker(sys.argv[2], sys.argv[3])
    elif mode == "all":
        for name in ("happy", "compensate", "retry", "crash", "isolation"):
            SCENARIOS[name]()
    else:
        SCENARIOS[mode]()
