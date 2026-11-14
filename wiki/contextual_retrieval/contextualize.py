# ollama 0.40.13, модель qwen2.5:7b, Python 3.12, прогнано на стенде 2026-11-14
"""Шаг индексации Contextual Retrieval: LLM пишет к каждому чанку короткий контекст.

Промпт взят из первоисточника Anthropic (anthropic.com/news/contextual-retrieval).
Документ стоит в начале промпта, чанк в конце. Поэтому у всех чанков одного документа
общий префикс, и Ollama берёт его из кэша, а не читает заново: локальный аналог prompt
caching из первоисточника. Сколько токенов пришло из кэша, Ollama отдаёт в нативном
/api/chat полем prompt_eval_cached_count.

Результат пишется в contexts.json: контекст и счётчики токенов по каждому чанку.
"""
import json
import os
import sys
import time
import urllib.request

from corpus import DOCUMENTS, whole_document

OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = "qwen2.5:7b"

# Промпт контекстуализации из первоисточника Anthropic, дословно
PROMPT = """<document>
{doc}
</document>
Here is the chunk we want to situate within the whole document
<chunk>
{chunk}
</chunk>
Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk. Answer only with the succinct context and nothing else."""


def chat(prompt):
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "30m",
        # temperature 0 и seed ради повторяемости; num_predict держит контекст в пределах 100 токенов
        "options": {"temperature": 0, "seed": 42, "num_predict": 100, "num_ctx": 4096},
    }
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)


def contextualize(doc_id, i):
    doc = whole_document(doc_id)
    resp = chat(PROMPT.format(doc=doc, chunk=DOCUMENTS[doc_id][i]))
    return {
        "context": resp["message"]["content"].strip(),
        # prompt_eval_count в 0.40.13 считает весь промпт, включая взятое из кэша
        "prompt_tokens": resp.get("prompt_eval_count", 0),
        "cached_tokens": resp.get("prompt_eval_cached_count", 0),
        "prompt_s": round(resp.get("prompt_eval_duration", 0) / 1e9, 1),
        "output_tokens": resp.get("eval_count", 0),
        "output_s": round(resp.get("eval_duration", 0) / 1e9, 1),
        "total_s": round(resp.get("total_duration", 0) / 1e9, 1),
    }


def main(limit=None):
    out, n = {}, 0
    t0 = time.time()
    print(f"{'чанк':22} {'промпт':>6} {'из кэша':>7} {'чтение,с':>8} {'ответ':>5} {'генерация,с':>11} {'всего,с':>7}")
    for doc_id, paragraphs in DOCUMENTS.items():
        for i in range(len(paragraphs)):
            if limit is not None and n >= limit:
                break
            r = contextualize(doc_id, i)
            out[f"{doc_id}#{i}"] = r
            n += 1
            print(f"{doc_id + '#' + str(i):22} {r['prompt_tokens']:6} {r['cached_tokens']:7} "
                  f"{r['prompt_s']:8} {r['output_tokens']:5} {r['output_s']:11} {r['total_s']:7}", flush=True)
    wall = time.time() - t0

    # Сводка по кэшу: первый чанк документа против остальных
    first = [v for k, v in out.items() if k.endswith("#0")]
    rest = [v for k, v in out.items() if not k.endswith("#0")]
    total_prompt = sum(v["prompt_tokens"] for v in out.values())
    total_cached = sum(v["cached_tokens"] for v in out.values())
    print(f"\nвызовов: {n}, всего {wall:.0f} с, в среднем {wall / max(n, 1):.1f} с на чанк")
    print(f"токенов промпта: {total_prompt}, из них из кэша: {total_cached} "
          f"({100 * total_cached / max(total_prompt, 1):.0f}%)")
    for name, group in (("первый чанк документа", first), ("остальные чанки", rest)):
        if group:
            avg = lambda key: sum(v[key] for v in group) / len(group)
            print(f"{name}: в среднем промпт {avg('prompt_tokens'):.0f} ток., из кэша "
                  f"{avg('cached_tokens'):.0f}, чтение {avg('prompt_s'):.1f} с, ответ "
                  f"{avg('output_tokens'):.0f} ток. за {avg('output_s'):.1f} с")

    with open("contexts.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    key = "northwind_q1_2025#1"
    if key in out:
        print("\nчанк без контекста:\n ", DOCUMENTS["northwind_q1_2025"][1])
        print("контекст от модели:\n ", out[key]["context"])


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
