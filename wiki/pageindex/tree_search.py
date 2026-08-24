# pageindex 0.2.10, litellm 1.98.0, Ollama 0.32.13, модель qwen2.5:7b, прогон 2026-08-24
"""Reasoning-поиск по дереву PageIndex: модель выбирает узел, потом отвечает по нему."""
import json
import re
import time

import litellm
import pypdfium2 as pdfium

MODEL = "ollama/qwen2.5:7b"
PDF = "annual_report.pdf"
QUESTION = "What did the Federal Reserve do about crypto-asset supervision?"


def flatten(nodes, out=None, path=""):
    """Разворачивает дерево в плоский список узлов с путём от корня."""
    out = [] if out is None else out
    for node in nodes:
        full = f'{path} > {node["title"]}' if path else node["title"]
        out.append({
            "node_id": f'{len(out):04d}',
            "title": full,
            "start": node["start_index"],
            "end": node["end_index"],
        })
        flatten(node.get("nodes", []), out, full)
    return out


def ask(prompt):
    """Один синхронный вызов локальной модели через LiteLLM."""
    response = litellm.completion(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        num_ctx=8192,
        timeout=900,
    )
    return response.choices[0].message.content


def pages_text(start, end):
    """Достаёт текст диапазона страниц PDF, страницы нумеруются с единицы."""
    doc = pdfium.PdfDocument(PDF)
    chunks = []
    for page_no in range(start - 1, min(end, len(doc))):
        chunks.append(doc[page_no].get_textpage().get_text_range())
    return "\n".join(chunks)


if __name__ == "__main__":
    with open("tree.json", encoding="utf-8") as f:
        nodes = flatten(json.load(f))

    # шаг 1: модель видит только оглавление, а не текст документа
    toc = "\n".join(f'{n["node_id"]}: {n["title"]} (pages {n["start"]}-{n["end"]})'
                    for n in nodes)
    select_prompt = (
        f"Here is the table of contents of a document.\n\n{toc}\n\n"
        f'Question: "{QUESTION}"\n'
        "Which single section most likely contains the answer? "
        'Reply with JSON only: {"node_id": "0000", "reason": "..."}'
    )
    start = time.time()
    raw = ask(select_prompt)
    print("Ответ модели на шаге выбора узла:")
    print(raw.strip())

    chosen_id = re.search(r'"node_id"\s*:\s*"?(\d+)"?', raw).group(1).zfill(4)
    node = next(n for n in nodes if n["node_id"] == chosen_id)
    print(f'\nВыбран узел {chosen_id}: {node["title"]} '
          f'(страницы {node["start"]}-{node["end"]})')
    print(f"Шаг выбора занял {time.time() - start:.1f} с")

    # шаг 2: в контекст уходят только страницы выбранного узла
    text = pages_text(node["start"], node["end"])
    print(f"В контекст ушло {len(text)} символов вместо всего документа")

    start = time.time()
    answer = ask(f"Answer the question using only this text.\n\n{text}\n\n"
                 f"Question: {QUESTION}\nAnswer in three sentences.")
    print(f"\nОтвет (получен за {time.time() - start:.1f} с):")
    print(answer.strip())
