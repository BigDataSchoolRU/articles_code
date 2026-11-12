# llama.cpp v0.9.0 (b12110), Qwen2.5-7B-Instruct Q4_K_M, прогнано на стенде 2026-11-12 (CPU, 4 vCPU)
"""Почему ответ со спекуляцией разошёлся с baseline при temperature 0.

Целевая модель проверяет черновик одним батчем из нескольких токенов, а без спекуляции
считает по одному токену. На CPU для батча и для одиночного токена llama.cpp идёт разными
путями матричного умножения, и logprob кандидатов сдвигается на сотые и десятые доли.
Если у двух кандидатов вероятности почти равны, argmax переворачивается. Скрипт читает один и тот же префикс ответа дважды: батчем
(-ub 512, как при проверке черновика) и строго по одному токену (-ub 1, как при обычной
генерации), и печатает top-3 кандидата на следующий токен.
"""
import json
import pathlib
import subprocess
import time
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
LLAMA = HERE / "llama.cpp" / "llama-server"
TARGET = HERE / "models" / "qwen2.5_7b_instruct_q4_k_m.gguf"
PORT = 8091

# Префикс ответа взят из прогона spec_bench.py: ровно до токена, на котором ответ
# со спекуляцией впервые разошёлся с baseline («море тихо шепчет» против «море шептало»).
TASK = "creative_story"
PREFIX = "В ночи, когда море"


def http(path, body=None, timeout=900):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def top_next(prompt_text, prefix):
    # Шаблон чата Qwen применяет сам сервер, затем дописываем начало ответа модели
    tpl = http("/apply-template", {"messages": [{"role": "user", "content": prompt_text}]})["prompt"]
    r = http("/completion", {"prompt": tpl + prefix, "n_predict": 1, "n_probs": 3,
                             "temperature": 0, "cache_prompt": False})
    return [(p["token"], p["logprob"]) for p in r["completion_probabilities"][0]["top_logprobs"]]


def main():
    prompt = (HERE / "prompts" / f"{TASK}.txt").read_text()
    (HERE / "outputs").mkdir(exist_ok=True)
    for ub in ("512", "1"):
        log = open(HERE / "outputs" / f"server_tie_ub{ub}.log", "w")
        proc = subprocess.Popen([str(LLAMA), "-m", str(TARGET), "-c", "4096", "-t", "4", "-np", "1",
                                 "-b", "512", "-ub", ub, "--port", str(PORT)], stdout=log, stderr=subprocess.STDOUT)
        try:
            while True:
                try:
                    http("/health", timeout=2)
                    break
                except Exception:
                    time.sleep(1)
            print(f"\n=== префикс читается {'батчем, -ub 512' if ub == '512' else 'по одному токену, -ub 1'} ===", flush=True)
            tops = top_next(prompt, PREFIX)
            shown = "  ".join(f"{tok!r} {lp:.4f}" for tok, lp in tops)
            print(f"{PREFIX!r} -> {shown}", flush=True)
        finally:
            proc.terminate()
            proc.wait()
            log.close()


if __name__ == "__main__":
    main()
