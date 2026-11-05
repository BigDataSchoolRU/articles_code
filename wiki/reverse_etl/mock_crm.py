# Python 3.12.3, только стандартная библиотека, прогнано на стенде 2026-11-05
"""Имитация API CRM: upsert и удаление контактов по внешнему ключу, лимит запросов с 429.

Эндпоинты:
  POST /objects/<объект>/upsert  {"records": [{"external_id": "...", ...}]}
  POST /objects/<объект>/delete  {"external_ids": ["...", ...]}
  GET  /objects/<объект>         записи и счётчики объекта
  GET  /health
"""
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("CRM_HOST", "127.0.0.1")
PORT = int(os.environ.get("CRM_PORT", "18080"))
RATE_LIMIT = int(os.environ.get("CRM_RATE_LIMIT", "2"))   # запросов на запись в окно
WINDOW_S = float(os.environ.get("CRM_WINDOW_S", "1.0"))   # длина окна, секунды
MAX_BATCH = int(os.environ.get("CRM_MAX_BATCH", "10"))    # записей в одном запросе

lock = threading.Lock()
objects = {}  # объект -> {"records": {external_id: поля}, "stats": {...}}
window = {"start": time.monotonic(), "count": 0}


def get_object(name):
    return objects.setdefault(name, {
        "records": {},
        "stats": {"write_requests": 0, "throttled": 0, "upserted": 0, "deleted": 0},
    })


def take_slot():
    """Фиксированное окно: RATE_LIMIT запросов на WINDOW_S секунд. Возвращает 0 или Retry-After."""
    now = time.monotonic()
    if now - window["start"] >= WINDOW_S:
        window["start"], window["count"] = now, 0
    if window["count"] < RATE_LIMIT:
        window["count"] += 1
        return 0
    return max(1, math.ceil(WINDOW_S - (now - window["start"])))


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, headers=None):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if parts == ["health"]:
            return self.reply(200, {"status": "ok"})
        if len(parts) == 2 and parts[0] == "objects":
            with lock:
                obj = get_object(parts[1])
                return self.reply(200, {"count": len(obj["records"]),
                                        "stats": obj["stats"], "records": obj["records"]})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "objects" or parts[2] not in ("upsert", "delete"):
            return self.reply(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        with lock:
            obj = get_object(parts[1])
            # лимит проверяется до разбора тела запроса: отказ 429 ничего не меняет в данных
            retry_after = take_slot()
            if retry_after:
                obj["stats"]["throttled"] += 1
                return self.reply(429, {"error": "rate limit exceeded"},
                                  {"Retry-After": str(retry_after)})
            obj["stats"]["write_requests"] += 1
            if parts[2] == "upsert":
                records = body.get("records", [])
                if len(records) > MAX_BATCH:
                    return self.reply(413, {"error": f"batch > {MAX_BATCH} records"})
                for rec in records:
                    if not rec.get("external_id") or not rec.get("email"):
                        return self.reply(400, {"error": "external_id and email required"})
                for rec in records:
                    # upsert по внешнему ключу: есть запись — обновить, нет — создать
                    obj["records"][rec["external_id"]] = {k: v for k, v in rec.items()
                                                          if k != "external_id"}
                obj["stats"]["upserted"] += len(records)
                return self.reply(200, {"upserted": len(records)})
            ids = body.get("external_ids", [])
            removed = sum(1 for i in ids if obj["records"].pop(i, None) is not None)
            obj["stats"]["deleted"] += removed
            return self.reply(200, {"deleted": removed, "not_found": len(ids) - removed})

    def log_message(self, fmt, *args):
        pass  # без access-лога, вывод прогона читается по строкам sync.py


if __name__ == "__main__":
    print(f"mock CRM на http://{HOST}:{PORT}, лимит {RATE_LIMIT} запросов/{WINDOW_S} с, "
          f"батч до {MAX_BATCH} записей", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
