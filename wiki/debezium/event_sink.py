# HTTP-приёмник событий Debezium, прогнан на Python 3.12.13
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = sys.argv[1] if len(sys.argv) > 1 else "events.jsonl"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8099


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        # Debezium Server шлёт тело события обычным POST с JSON внутри
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(body + "\n")
        # короткая строка в консоль, чтобы прогон было видно вживую
        try:
            evt = json.loads(body)
            op = evt.get("op") or evt.get("__op") or "?"
            print(f"событие op={op} {json.dumps(evt, ensure_ascii=False)[:120]}")
        except json.JSONDecodeError:
            print(f"не JSON: {body[:120]}")
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        # глушим стандартный лог http.server, он мешает читать вывод
        pass


if __name__ == "__main__":
    print(f"приёмник слушает 0.0.0.0:{PORT}, пишет в {OUT}")
    HTTPServer(("0.0.0.0", PORT), Sink).serve_forever()
