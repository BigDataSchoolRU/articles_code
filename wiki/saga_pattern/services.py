# psycopg 3.3.8, postgres 18.6, прогнано на стенде 2026-11-12
"""Три сервиса интернет-магазина: заказы, склад, оплата.

У каждого своя база. Каждая функция это одна локальная ACID-транзакция в базе своего сервиса:
блок `with connect(...)` коммитит при нормальном выходе и откатывает при исключении.
Компенсации (cancel_order, release_stock) это тоже обычные локальные транзакции, а не ROLLBACK:
к моменту компенсации шаг, который они отменяют, давно закоммичен.
"""
import os

import psycopg

DSN = os.environ.get("SAGA_DSN", "host=127.0.0.1 port=55440 user=demo password=demo")


def connect(db: str) -> psycopg.Connection:
    return psycopg.connect(f"{DSN} dbname={db}")


class BusinessError(Exception):
    """Нарушено бизнес-правило: повтор не поможет, сага уходит в компенсацию."""


class OutOfStock(BusinessError):
    pass


class PaymentDeclined(BusinessError):
    pass


class TransientError(Exception):
    """Временный сбой: шаг можно повторить с тем же ключом идемпотентности."""


class StockLocked(TransientError):
    """Товар держит резерв другой незавершённой саги (semantic lock): ждём, а не отказываем."""


# ── Сервис заказов ──────────────────────────────────────────────────────────
def create_order(saga_id: str, p: dict, idem_key: str) -> str:
    with connect("orders") as conn:
        cur = conn.execute(
            """INSERT INTO orders (order_id, customer, sku, qty, amount, status)
               VALUES (%s, %s, %s, %s, %s, 'PENDING')
               ON CONFLICT (order_id) DO NOTHING RETURNING order_id""",
            (saga_id, p["customer"], p["sku"], p["qty"], p["amount"]),
        )
        return "заказ PENDING" if cur.fetchone() else "повтор: заказ уже создан"


def cancel_order(saga_id: str, p: dict) -> str:
    # компенсация create_order: заказ не удаляется, а получает статус CANCELLED
    with connect("orders") as conn:
        cur = conn.execute(
            "UPDATE orders SET status = 'CANCELLED', updated_at = now() "
            "WHERE order_id = %s AND status = 'PENDING'",
            (saga_id,),
        )
        return f"заказ CANCELLED (строк {cur.rowcount})"


def confirm_order(saga_id: str, p: dict, idem_key: str) -> str:
    # повторяемый шаг после pivot: условие по статусу делает его идемпотентным
    with connect("orders") as conn:
        cur = conn.execute(
            "UPDATE orders SET status = 'APPROVED', updated_at = now() "
            "WHERE order_id = %s AND status = 'PENDING'",
            (saga_id,),
        )
        return f"заказ APPROVED (строк {cur.rowcount})"


# ── Сервис склада ───────────────────────────────────────────────────────────
def reserve_stock(saga_id: str, p: dict, idem_key: str, semantic_lock: bool = False) -> str:
    with connect("inventory") as conn:
        # ключ идемпотентности: повтор того же шага саги не создаёт второй резерв
        cur = conn.execute(
            """INSERT INTO reservations (idem_key, saga_id, sku, qty, status)
               VALUES (%s, %s, %s, %s, 'PENDING')
               ON CONFLICT (idem_key) DO NOTHING RETURNING idem_key""",
            (idem_key, saga_id, p["sku"], p["qty"]),
        )
        if cur.fetchone() is None:
            return "повтор: резерв с этим ключом уже есть, остаток не трогаем"
        row = conn.execute(
            "UPDATE stock SET available = available - %s "
            "WHERE sku = %s AND available >= %s RETURNING available",
            (p["qty"], p["sku"], p["qty"]),
        ).fetchone()
        if row is None:
            # исключение откатывает и INSERT резерва выше: локальная транзакция атомарна
            if semantic_lock:
                held = conn.execute(
                    "SELECT count(*) FROM reservations "
                    "WHERE sku = %s AND status = 'PENDING' AND saga_id <> %s",
                    (p["sku"], saga_id),
                ).fetchone()[0]
                if held:
                    raise StockLocked(f"{p['sku']}: товар в резерве у незавершённой саги ({held})")
            raise OutOfStock(f"{p['sku']}: нет на складе")
        return f"резерв {p['qty']} шт., остаток {row[0]}"


def release_stock(saga_id: str, p: dict) -> str:
    # компенсация reserve_stock: снимаем все незавершённые резервы саги и возвращаем товар
    with connect("inventory") as conn:
        rows = conn.execute(
            "UPDATE reservations SET status = 'RELEASED', updated_at = now() "
            "WHERE saga_id = %s AND status = 'PENDING' RETURNING sku, qty",
            (saga_id,),
        ).fetchall()
        for sku, qty in rows:
            conn.execute(
                "UPDATE stock SET available = available + %s WHERE sku = %s", (qty, sku)
            )
        return f"резерв снят, вернули {sum(q for _, q in rows)} шт."


def commit_reservation(saga_id: str, p: dict, idem_key: str) -> str:
    # повторяемый шаг после pivot: резерв PENDING становится COMMITTED, semantic lock снят
    with connect("inventory") as conn:
        cur = conn.execute(
            "UPDATE reservations SET status = 'COMMITTED', updated_at = now() "
            "WHERE saga_id = %s AND status = 'PENDING'",
            (saga_id,),
        )
        return f"резерв COMMITTED (строк {cur.rowcount})"


# ── Сервис оплаты ───────────────────────────────────────────────────────────
def charge_payment(saga_id: str, p: dict, idem_key: str) -> str:
    with connect("payments") as conn:
        cur = conn.execute(
            """INSERT INTO payments (idem_key, saga_id, customer, amount, status)
               VALUES (%s, %s, %s, %s, 'CHARGED')
               ON CONFLICT (idem_key) DO NOTHING RETURNING idem_key""",
            (idem_key, saga_id, p["customer"], p["amount"]),
        )
        if cur.fetchone() is None:
            return "повтор: платёж с этим ключом уже проведён"
        row = conn.execute(
            "UPDATE accounts SET balance = balance - %s "
            "WHERE customer = %s AND balance >= %s RETURNING balance",
            (p["amount"], p["customer"], p["amount"]),
        ).fetchone()
        if row is None:
            raise PaymentDeclined(f"{p['customer']}: недостаточно средств для {p['amount']}")
        return f"списано {p['amount']}, баланс {row[0]}"
