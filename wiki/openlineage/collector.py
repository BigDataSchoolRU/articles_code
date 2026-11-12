# Python 3.12 stdlib, без зависимостей; прогнано на стенде 2026-11-12 с openlineage-python 1.55.0 и openlineage-spark 1.55.0
"""Минимальный потребитель событий OpenLineage.

serve  принимает POST /api/v1/lineage (тот же путь, что у Marquez) и дописывает событие строкой в events.jsonl
graph  читает events.jsonl и собирает граф «датасет -> задание -> датасет» по namespace и name
show   печатает одно событие целиком: collector.py show build_daily_revenue COMPLETE

Задача файла показать, что потребителем может быть кто угодно, кто понимает формат события:
граф получается склейкой датасетов с одинаковой парой namespace и name.
"""
import argparse
import json
import sys
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def serve(host: str, port: int, out: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/api/v1/lineage":
                self.send_response(404)
                self.end_headers()
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            event = json.loads(body)
            # одна строка на событие, порядок прихода сохраняется
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            kind = event.get("eventType") or ("JobEvent" if "job" in event else "DatasetEvent")
            job = event.get("job", {})
            print(f"принято {kind:<8} {job.get('namespace', '-')}/{job.get('name', '-')}", flush=True)
            self.send_response(201)
            self.end_headers()

        def log_message(self, *args):  # стандартный журнал запросов не нужен
            pass

    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"сборщик слушает http://{host}:{port}/api/v1/lineage, пишет в {out}", flush=True)
    srv.serve_forever()


def ds_key(ds: dict) -> str:
    # ключ склейки графа: пара namespace и name, больше ничего
    return f"{ds['namespace']}::{ds['name']}"


def graph(path: Path) -> None:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"событий в журнале: {len(events)}")

    by_state = defaultdict(int)
    producers = defaultdict(int)
    for e in events:
        by_state[e.get("eventType", "-")] += 1
        producers[e["producer"]] += 1
    print("по типам:", dict(sorted(by_state.items())))
    for p, n in producers.items():
        print(f"производитель {p}: {n}")

    # Задание -> множество входов и выходов. Spark присылает датасеты частями в START, RUNNING и
    # COMPLETE, поэтому складываем всё по заданию, а не берём одно событие.
    jobs = defaultdict(lambda: {"in": set(), "out": set(), "states": [], "col": {}})
    for e in events:
        if "job" not in e or "run" not in e:
            continue
        j = jobs[f"{e['job']['namespace']}/{e['job']['name']}"]
        j["states"].append(e["eventType"])
        j["in"].update(ds_key(d) for d in e.get("inputs") or [])
        for d in e.get("outputs") or []:
            j["out"].add(ds_key(d))
            col = (d.get("facets") or {}).get("columnLineage")
            if col:
                j["col"][ds_key(d)] = col
        facets = e["run"].get("facets") or {}
        if facets.get("errorMessage"):
            j["error"] = facets["errorMessage"]["message"]
        if facets.get("parent"):
            p = facets["parent"]["job"]
            j["parent"] = f"{p['namespace']}/{p['name']}"

    print("\nзадания с датасетами:")
    edges = []
    for name, j in sorted(jobs.items()):
        if not j["in"] and not j["out"]:
            continue
        states = " ".join(j["states"])
        print(f"  {name}\n    события: {states}")
        if "parent" in j:
            print(f"    родительское задание: {j['parent']}")
        if "error" in j:
            print(f"    ошибка: {j['error']}")
        for i in sorted(j["in"]):
            print(f"    вход  {i}")
            edges.append((i, name))
        for o in sorted(j["out"]):
            print(f"    выход {o}")
            edges.append((name, o))
    skipped = [n for n, j in jobs.items() if not j["in"] and not j["out"]]
    print(f"  заданий без датасетов (служебные события запуска): {len(skipped)}")

    # Компоненты связности: сколько несвязанных кусков графа получилось
    adj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    seen, comps = set(), []
    for node in adj:
        if node in seen:
            continue
        stack, comp = [node], set()
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            comp.add(n)
            stack.extend(adj[n] - seen)
        comps.append(comp)
    print(f"\nкомпонент связности графа: {len(comps)}")
    for k, comp in enumerate(comps, 1):
        datasets = sorted(n for n in comp if "::" in n)
        print(f"  [{k}] датасетов {len(datasets)}, заданий {len(comp) - len(datasets)}")
        for d in datasets:
            print(f"      {d}")

    print("\nколоночный lineage (поле выхода <- поля входов):")
    for name, j in sorted(jobs.items()):
        for out, col in sorted(j["col"].items()):
            print(f"  {out}")
            for field, spec in col.get("fields", {}).items():
                src = ", ".join(
                    f"{f['name'].rsplit('/', 1)[-1]}.{f['field']} "
                    f"[{'/'.join(t.get('type', '') + ':' + t.get('subtype', '') for t in f.get('transformations') or [])}]"
                    for f in spec["inputFields"]
                )
                print(f"    {field:<10} <- {src}")
            for f in col.get("dataset") or []:
                t = "/".join(x.get("type", "") + ":" + x.get("subtype", "") for x in f.get("transformations") or [])
                print(f"    (весь датасет) <- {f['name'].rsplit('/', 1)[-1]}.{f['field']} [{t}]")


def show(path: Path, job: str, state: str) -> None:
    # одно событие целиком, как его видит потребитель
    for line in path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("job", {}).get("name") == job and e.get("eventType") == state:
            print(json.dumps(e, ensure_ascii=False, indent=2))
            return
    print(f"нет события {state} для задания {job}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5000)
    s.add_argument("--out", type=Path, default=HERE / "events.jsonl")
    g = sub.add_parser("graph")
    g.add_argument("path", type=Path, nargs="?", default=HERE / "events.jsonl")
    w = sub.add_parser("show")
    w.add_argument("job")
    w.add_argument("state", nargs="?", default="COMPLETE")
    w.add_argument("--path", type=Path, default=HERE / "events.jsonl")
    a = ap.parse_args()
    if a.cmd == "serve":
        serve(a.host, a.port, a.out)
    elif a.cmd == "show":
        show(a.path, a.job, a.state)
    else:
        graph(a.path)


if __name__ == "__main__":
    sys.exit(main())
