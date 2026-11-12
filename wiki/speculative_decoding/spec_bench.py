# llama.cpp v0.9.0 (b12110), Qwen2.5-7B-Instruct Q4_K_M + Qwen2.5-0.5B-Instruct q8_0, прогнано на стенде 2026-11-12 (CPU, 4 vCPU)
"""Замер speculative decoding в llama-server: скорость генерации, доля принятых токенов
черновика и побайтное совпадение ответа с генерацией без спекуляции.

Для каждой конфигурации скрипт поднимает свой llama-server, отправляет промпты из ./prompts
с temperature 0 (greedy) и гасит сервер. Только стандартная библиотека Python.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent

# Конфигурации: имя -> дополнительные флаги llama-server.
# draft-simple: отдельная малая модель с тем же словарём пишет черновик.
# ngram-simple и ngram-mod: черновик берётся из уже увиденного текста, второй модели нет.
CONFIGS = {
    "baseline":       [],
    "draft_n_max_3":  ["--spec-type", "draft-simple", "-md", "{draft}", "--spec-draft-n-max", "3"],
    "draft_n_max_8":  ["--spec-type", "draft-simple", "-md", "{draft}", "--spec-draft-n-max", "8"],
    "ngram_simple":   ["--spec-type", "ngram-simple"],
    "ngram_mod":      ["--spec-type", "ngram-mod"],
}


def http(port, path, body=None, timeout=1800):
    """GET без тела, POST с JSON-телом; возвращает разобранный JSON."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def start_server(args, extra, log_path):
    """Поднимает llama-server с целевой моделью и ждёт, пока /health ответит 200."""
    cmd = [str(args.llama_dir / "llama-server"), "-m", str(args.target),
           "-c", "4096", "-t", str(args.threads), "-np", "1", "--port", str(args.port)]
    cmd += [a.replace("{draft}", str(args.draft)) for a in extra]
    log = open(log_path, "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server упал при старте, см. {log_path}")
        try:
            http(args.port, "/health", timeout=2)
            return proc, log, time.time() - t0
        except Exception:
            time.sleep(1)


def ask(args, prompt):
    """Один запрос к целевой модели. temperature 0 даёт greedy-декодирование,
    cache_prompt false заставляет каждый повтор заново читать промпт."""
    body = {"messages": [{"role": "user", "content": prompt}],
            "max_tokens": args.n_predict, "temperature": 0, "cache_prompt": False}
    return http(args.port, "/v1/chat/completions", body)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--llama-dir", type=pathlib.Path, default=HERE / "llama.cpp")
    p.add_argument("--target", type=pathlib.Path, default=HERE / "models/qwen2.5_7b_instruct_q4_k_m.gguf")
    p.add_argument("--draft", type=pathlib.Path, default=HERE / "models/qwen2.5_0.5b_instruct_q8_0.gguf")
    p.add_argument("--n-predict", type=int, default=256)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--configs", default=",".join(CONFIGS))
    args = p.parse_args()

    prompts = {f.stem: f.read_text() for f in sorted((HERE / "prompts").glob("*.txt"))}
    out_dir = HERE / "outputs"
    out_dir.mkdir(exist_ok=True)
    rows = []

    for name in args.configs.split(","):
        proc, log, load_s = start_server(args, CONFIGS[name], out_dir / f"server_{name}.log")
        flags = " ".join(a.replace("{draft}", args.draft.name) for a in CONFIGS[name]) or "(без спекуляции)"
        print(f"\n=== {name}: сервер поднят за {load_s:.1f} с, флаги: {flags}", flush=True)
        try:
            for task, prompt in prompts.items():
                for rep in range(1, args.repeats + 1):
                    r = ask(args, prompt)
                    text = r["choices"][0]["message"]["content"]
                    t = r["timings"]
                    sha = hashlib.sha256(text.encode()).hexdigest()[:12]
                    (out_dir / f"{name}_{task}.txt").write_text(text)
                    row = {"config": name, "task": task, "rep": rep,
                           "tokens": t["predicted_n"], "tok_s": t["predicted_per_second"],
                           "draft_n": t.get("draft_n", 0), "accepted": t.get("draft_n_accepted", 0),
                           "sha": sha}
                    rows.append(row)
                    acc = f"{row['accepted']}/{row['draft_n']}" if row["draft_n"] else "-"
                    print(f"{task:14} #{rep} токенов {row['tokens']:4}  {row['tok_s']:5.2f} ток/с  "
                          f"принято {acc:>9}  sha256 {sha}", flush=True)
        finally:
            proc.terminate()
            proc.wait()
            log.close()
        # Сводка приёма из лога сервера: строка "draft acceptance = ... (accepted / generated)"
        for line in (out_dir / f"server_{name}.log").read_text().splitlines():
            if "draft acceptance" in line:
                print("  лог:", line.split("|")[-1].strip())

    # Итоговая таблица. Значения по каждому повтору через «/»: ngram-mod копит статистику
    # между запросами одного сервера, и второй повтор у него не равен первому.
    print(f"\n=== СВОДКА (temperature 0, n_predict {args.n_predict}, повторы через /) ===")
    print(f"{'конфигурация':15} {'задача':14} {'ток/с':>13} {'ускорение':>13} {'приём':>15} {'ток/проход':>10}  ответ = baseline")
    base = {}
    for task in prompts:
        for name in args.configs.split(","):
            rs = [r for r in rows if r["config"] == name and r["task"] == task]
            if not rs:
                continue
            if name == "baseline":
                base[task] = (sum(r["tok_s"] for r in rs) / len(rs), rs[0]["sha"])
            gen = sum(r["draft_n"] for r in rs)
            acc = sum(r["accepted"] for r in rs)
            tokens = sum(r["tokens"] for r in rs)
            # Каждый проход целевой модели даёт принятые токены черновика плюс один свой,
            # значит проходов было tokens - accepted
            per_pass = tokens / max(tokens - acc, 1)
            rate = f"{acc / gen:.2f} ({acc}/{gen})" if gen else "-"
            speeds = " / ".join(f"{r['tok_s']:.2f}" for r in rs)
            ups = " / ".join(f"x{r['tok_s'] / base[task][0]:.2f}" for r in rs) if task in base else "-"
            same = " / ".join("да" if r["sha"] == base[task][1] else "нет" for r in rs) if task in base else "-"
            print(f"{name:15} {task:14} {speeds:>13} {ups:>13} {rate:>15} {per_pass:10.2f}  {same}")


if __name__ == "__main__":
    main()
