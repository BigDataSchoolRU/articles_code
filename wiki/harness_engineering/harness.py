# Python 3.12 stdlib, ollama 0.40.13, модели qwen2.5:7b и llama3.1:8b, прогнано на стенде 2026-11-05
"""Минимальный harness поверх Ollama: та же модель и та же задача, что в bare.py.

Вокруг модели пять частей:
  инструменты  - read_file и run_tests в формате tool calling Ollama;
  формат правки - новый duration.py модель присылает блоком ```python в тексте ответа,
                 harness сам записывает его в файл (код внутри JSON-аргумента малые модели
                 ломают, и Ollama такой вызов молча выбрасывает);
  контекст     - короткая инструкция-карта и файл прогресса progress.md;
  песочница    - копия задачи во временной папке, читать можно только внутри неё,
                 записывается только duration.py, тесты агенту недоступны для правки;
  проверка     - после каждой правки harness сам гоняет тесты и возвращает ошибки модели;
  детектор петли - если модель прислала код, который уже был, harness говорит ей об этом
                 и просит сменить подход, а не прогоняет то же самое молча;
  цикл         - шаги до прохождения тестов или до исчерпания бюджета MAX_STEPS.
"""
import ast
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
MAX_STEPS = int(os.environ.get("MAX_STEPS", "8"))
TASK_DIR = Path(__file__).resolve().parent / "task"
TARGET = "duration.py"              # единственный файл, который harness перезаписывает
FEEDBACK_LIMIT = 1500               # сколько символов вывода тестов отдаём модели
NUM_PREDICT = 900                   # потолок токенов на шаг: бюджет времени на CPU
TRACE = os.environ.get("TRACE")     # путь к jsonl с сырыми ответами модели, для разбора

# Контекст: карта задачи, а не энциклопедия. Всё остальное агент читает инструментами.
INSTRUCTIONS = """Ты агент, который пишет код в рабочей папке.
Правила:
1. Прочитай duration.py и test_duration.py инструментом read_file.
2. Новый duration.py присылай целиком в тексте ответа одним блоком ```python,
   без пояснений и без docstring. Не передавай код через инструменты:
   harness сам запишет блок в файл.
3. После каждой правки тесты прогоняются автоматически, результат придёт следующим сообщением.
4. Тесты менять нельзя.
Задача решена, когда проходят все тесты."""

TOOLS = [
    {"type": "function", "function": {
        "name": "read_file", "description": "Прочитать файл из рабочей папки",
        "parameters": {"type": "object", "required": ["path"],
                       "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "run_tests", "description": "Прогнать тесты test_duration.py",
        "parameters": {"type": "object", "properties": {}}}},
]


def chat(messages):
    # один шаг модели; temperature 0 и seed, чтобы прогон повторялся
    body = {"model": MODEL, "messages": messages, "tools": TOOLS, "stream": False,
            "options": {"temperature": 0, "seed": 42, "num_ctx": 8192,
                        "num_predict": NUM_PREDICT}}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = json.load(resp)
    return data["message"], data.get("eval_count", 0)


class Sandbox:
    """Песочница: копия задачи во временной папке и проверка путей."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="harness_")).resolve()
        shutil.copytree(TASK_DIR, self.root, dirs_exist_ok=True)
        self.progress = self.root / "progress.md"
        self.progress.write_text("# Прогресс агента\n")

    def path(self, name):
        p = (self.root / name).resolve()
        if p.parent != self.root:
            raise PermissionError(f"путь вне рабочей папки: {name}")
        return p

    def run_tests(self):
        proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_duration"],
                              cwd=self.root, capture_output=True, text=True, timeout=30)
        out = proc.stdout + proc.stderr
        total = int(m.group(1)) if (m := re.search(r"Ran (\d+) test", out)) else 0
        bad = sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", out))
        return total - bad, total, out


def feedback(passed, total, out):
    # Проверяющая петля: модели уходит итог, имена упавших тестов и хвост ошибок, а не весь лог
    head = f"тестов прошло {passed} из {total}"
    if passed == total and total:
        return head + ". Все тесты прошли."
    failed = re.findall(r"^(?:FAIL|ERROR): (\w+)", out, re.M)
    return (head + ". Упали: " + ", ".join(failed) + ".\nХвост вывода:\n"
            + out[-FEEDBACK_LIMIT:])


def fingerprint(code):
    # отпечаток кода без форматирования и комментариев; не парсится - берём текст как есть
    try:
        return ast.dump(ast.parse(code))
    except SyntaxError:
        return code.strip()


def main():
    box = Sandbox()
    messages = [{"role": "system", "content": INSTRUCTIONS},
                {"role": "user", "content": "Реализуй parse_duration в duration.py."}]
    state = {"passed": 0, "total": 0, "tool_calls": 0, "refused": 0, "edits": 0, "empty": 0,
             "loops": 0}
    seen = {}                       # отпечаток кода -> (шаг, прошло, всего)

    def check(step):
        # прогон тестов и строка в progress.md: мост для следующей сессии агента
        passed, total, out = box.run_tests()
        state.update(passed=passed, total=total)
        with box.progress.open("a") as f:
            f.write(f"- шаг {step}: тестов прошло {passed} из {total}\n")
        return feedback(passed, total, out)

    def execute(step, name, args):
        state["tool_calls"] += 1
        try:
            if name == "read_file":
                return box.path(args["path"]).read_text()
            if name == "run_tests":
                return check(step)
            return f"нет такого инструмента: {name}"
        except PermissionError as e:
            state["refused"] += 1
            return f"отказано: {e}"
        except (OSError, KeyError, subprocess.TimeoutExpired) as e:
            return f"ошибка инструмента: {type(e).__name__}: {e}"

    t0 = time.time()
    step = 0
    for step in range(1, MAX_STEPS + 1):
        ts = time.time()
        msg, tokens = chat(messages)
        messages.append(msg)
        if TRACE:
            with open(TRACE, "a") as f:
                f.write(json.dumps({"step": step, "eval_count": tokens, "message": msg},
                                   ensure_ascii=False) + "\n")
        calls = msg.get("tool_calls") or []
        notes = []
        for call in calls:
            name = call["function"]["name"]
            args = call["function"].get("arguments") or {}
            if isinstance(args, str):           # часть моделей отдаёт аргументы строкой
                args = json.loads(args or "{}")
            result = execute(step, name, args)
            messages.append({"role": "tool", "tool_name": name, "content": result})
            notes.append(f"{name}({args.get('path', '')})")
        blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", msg.get("content") or "", re.S)
        if blocks and (fp := fingerprint(blocks[-1])) in seen:
            # детектор петли: тот же код уже был, тесты не гоняем, просим другой подход
            state["loops"] += 1
            was, p_, t_ = seen[fp]
            messages.append({"role": "user", "content": (
                f"Этот код уже присылался на шаге {was} и дал {p_} из {t_} тестов. "
                "Повтор ничего не изменит. Перечитай упавшие тесты и смени подход к разбору "
                "строки, затем пришли новый duration.py целиком.")})
            notes.append(f"повтор кода шага {was}")
        elif blocks:
            # формат правки: последний блок кода из ответа harness кладёт в duration.py
            box.path(TARGET).write_text(blocks[-1])
            state["edits"] += 1
            messages.append({"role": "user", "content": check(step)})
            seen[fp] = (step, state["passed"], state["total"])
            notes.append(f"правка {TARGET}")
        elif not calls:
            # пустой ответ при сотнях токенов генерации: модель пыталась вызвать
            # инструмент, а Ollama не разобрала вызов и выбросила его целиком
            state["empty"] += 1
            messages.append({"role": "user", "content": "Ответ пришёл пустым. Пришли duration.py "
                             "целиком блоком ```python в тексте ответа, без вызова инструментов."})
            notes.append(f"пустой ответ ({tokens} токенов), напоминание")
        print(f"шаг {step} | {', '.join(notes)} | тестов {state['passed']}/{state['total']} "
              f"| {time.time() - ts:.1f} с", flush=True)
        if state["total"] and state["passed"] == state["total"]:
            break

    print(f"модель: {MODEL}")
    print(f"шагов модели: {step} из {MAX_STEPS}, правок кода: {state['edits']}, "
          f"повторов кода: {state['loops']}, вызовов инструментов: {state['tool_calls']}, "
          f"пустых ответов: {state['empty']}, "
          f"отказов песочницы: {state['refused']}, время: {time.time() - t0:.1f} с")
    print(f"тестов прошло: {state['passed']} из {state['total']}")
    print("progress.md:")
    print(box.progress.read_text().rstrip())
    shutil.rmtree(box.root)


if __name__ == "__main__":
    main()
