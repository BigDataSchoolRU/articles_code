# Python 3.12 stdlib, ollama 0.40.13, модели qwen2.5:7b и llama3.1:8b, прогнано на стенде 2026-11-05
"""Голая модель без harness: один запрос, один ответ, тесты гоняем только для оценки.

Модель видит ту же заготовку и те же тесты, что и агент в harness.py, но результат
проверки к ней не возвращается: что написала с первого раза, то и засчитано.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
TASK_DIR = Path(__file__).resolve().parent / "task"


def chat(messages):
    # один вызов /api/chat; temperature 0 и seed, чтобы прогон повторялся
    body = {"model": MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 900}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as resp:
        return json.load(resp)["message"]


def run_tests(workdir):
    # тот же unittest, что и в harness.py, с таймаутом на случай зависшего кода
    proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_duration"],
                          cwd=workdir, capture_output=True, text=True, timeout=30)
    out = proc.stdout + proc.stderr
    total = int(m.group(1)) if (m := re.search(r"Ran (\d+) test", out)) else 0
    bad = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", out))
    return total - bad, total, out


def main():
    workdir = Path(tempfile.mkdtemp(prefix="bare_"))
    shutil.copytree(TASK_DIR, workdir, dirs_exist_ok=True)
    stub = (workdir / "duration.py").read_text()
    tests = (workdir / "test_duration.py").read_text()

    prompt = ("Реализуй функцию parse_duration в файле duration.py так, чтобы прошли тесты.\n"
              "Верни полный текст duration.py одним блоком ```python,\n"
              "без пояснений и без docstring.\n\n"
              f"duration.py:\n```python\n{stub}```\n\ntest_duration.py:\n```python\n{tests}```")
    t0 = time.time()
    answer = chat([{"role": "user", "content": prompt}])["content"]
    elapsed = time.time() - t0

    # достаём код из ответа; если блока нет, считаем ответом весь текст
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", answer, re.S)
    (workdir / "duration.py").write_text(blocks[-1] if blocks else answer)

    passed, total, out = run_tests(workdir)
    print(f"модель: {MODEL}")
    print(f"вызовов модели: 1, время: {elapsed:.1f} с")
    print(f"тестов прошло: {passed} из {total}")
    if passed < total:
        # короткая выжимка упавших тестов, полную простыню не печатаем
        for line in out.splitlines():
            if line.startswith(("FAIL:", "ERROR:")):
                print("  " + line)
    shutil.rmtree(workdir)


if __name__ == "__main__":
    main()
