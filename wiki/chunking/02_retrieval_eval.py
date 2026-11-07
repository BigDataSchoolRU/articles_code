# langchain-text-splitters 1.1.3, llama-index-core 0.14.25, llama-index-embeddings-ollama 0.10.0, ollama 0.40.13 с nomic-embed-text, прогнано на стенде 2026-11-07
# Как стратегия и размер чанка влияют на поиск: hit rate@k и MRR по эталонным подстрокам, без LLM.
# Корпус: 8 Markdown-регламентов вымышленной компании, 24 вопроса с подстрокой ответа из корпуса.
import json
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import tiktoken
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)
from llama_index.core import Document
from llama_index.core.node_parser import SemanticSplitterNodeParser, SentenceSplitter
from llama_index.embeddings.ollama import OllamaEmbedding

HERE = Path(__file__).resolve().parent
OLLAMA = "http://localhost:11434"
MODEL = "nomic-embed-text"
SIZES = [128, 256, 512, 1024]  # размер чанка в токенах cl100k
TOP_K = 3
BUDGET = 512  # бюджет контекста для LLM в токенах: честное сравнение мелких и крупных чанков
CL100K = tiktoken.get_encoding("cl100k_base")

DOCS = {p.name: p.read_text(encoding="utf-8") for p in sorted((HERE / "corpus").glob("*.md"))}
QUESTIONS = [json.loads(line) for line in (HERE / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line]


def norm(text):
    # сплиттеры по-разному склеивают переводы строк, сравниваем текст без учёта пробельных символов
    return re.sub(r"\s+", " ", text)


def overflows(text):
    # не влезает ли чанк в окно модели: с truncate=false Ollama отвечает 400 вместо молчаливой обрезки
    body = {"model": MODEL, "input": ["search_document: " + text], "truncate": False, "keep_alive": "30m"}
    req = urllib.request.Request(OLLAMA + "/api/embed", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600):
            return False
    except urllib.error.HTTPError as e:
        return e.code == 400


def embed(texts):
    # nomic-embed-text обучена с префиксами задачи: search_document для чанков, search_query для вопросов
    out = []
    for i in range(0, len(texts), 32):
        body = {"model": MODEL, "input": texts[i:i + 32], "keep_alive": "30m"}
        req = urllib.request.Request(OLLAMA + "/api/embed", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            out.extend(json.load(r)["embeddings"])
    m = np.array(out, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


# --- стратегии: каждая возвращает список чанков-строк для одного документа ---

def fixed(text, size):
    # ровно size токенов, граница не смотрит ни на слова, ни на абзацы
    return TokenTextSplitter(encoding_name="cl100k_base", chunk_size=size, chunk_overlap=size // 8).split_text(text)


def recursive(text, size):
    # сначала абзацы, потом строки, потом слова; длина в токенах cl100k
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base", chunk_size=size, chunk_overlap=size // 8).split_text(text)


def markdown(text, size):
    # граница по заголовкам # и ##, длинный раздел дорезается рекурсивно;
    # заголовки документа и раздела дописываются в начало чанка как контекст
    sections = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "doc"), ("##", "section")]).split_text(text)
    chunks = []
    for s in sections:
        prefix = " / ".join(v for v in (s.metadata.get("doc"), s.metadata.get("section")) if v)
        for part in recursive(s.page_content, size):
            chunks.append(f"{prefix}\n{part}")
    return chunks


def sentence(text, size):
    # LlamaIndex: собирает чанк из целых предложений до size токенов
    return SentenceSplitter(chunk_size=size, chunk_overlap=size // 8).split_text(text)


def whole(text, size):
    # без разбиения: документ целиком как один чанк
    return [text]


SEMANTIC = SemanticSplitterNodeParser(
    buffer_size=1,
    breakpoint_percentile_threshold=95,
    embed_model=OllamaEmbedding(model_name=MODEL, base_url=OLLAMA, text_instruction="search_document: "),
)


def semantic(text, size):
    # граница там, где близость эмбеддингов соседних предложений резко падает; размер не задаётся
    return [n.get_content() for n in SEMANTIC.get_nodes_from_documents([Document(text=text)])]


def within_budget(order, chunks):
    # склеиваем найденные чанки по рангу, пока не кончится бюджет; последний обрезаем по токенам
    ids = []
    for i in order:
        ids.extend(CL100K.encode(chunks[i][1] + "\n"))
        if len(ids) >= BUDGET:
            break
    return norm(CL100K.decode(ids[:BUDGET]))


def evaluate(name, split, size, qvecs):
    t0 = time.time()
    chunks = [(doc, c) for doc, text in DOCS.items() for c in split(text, size)]
    t_split = time.time() - t0
    t0 = time.time()
    cvecs = embed(["search_document: " + c for _, c in chunks])
    t_embed = time.time() - t0

    texts = [norm(c) for _, c in chunks]
    sims = qvecs @ cvecs.T
    hits1 = hits3 = rr = cut = hits_budget = 0
    ctx_tokens = []
    for q, row in zip(QUESTIONS, sims):
        order = np.argsort(-row)
        gold = norm(q["answer"])
        if not any(gold in t for t in texts):
            cut += 1  # ответ разрезан границей чанка: ни один чанк не содержит его целиком
        ranks = [r for r, i in enumerate(order[:10], start=1) if gold in texts[i]]
        if ranks:
            rr += 1 / ranks[0]
            hits1 += ranks[0] == 1
            hits3 += ranks[0] <= TOP_K
        hits_budget += gold in within_budget(order, chunks)
        ctx_tokens.append(sum(len(CL100K.encode(chunks[i][1])) for i in order[:TOP_K]))
    n = len(QUESTIONS)
    toks = [len(CL100K.encode(c)) for _, c in chunks]
    # русский текст в токенизаторе nomic примерно вдвое длиннее, чем в cl100k: проверяем только длинные чанки
    over = sum(overflows(c) for (_, c), t in zip(chunks, toks) if t > 800)
    print(f"{name:<10} {size if size else '—':>5} | чанков {len(chunks):>3} | сред. токенов {round(statistics.mean(toks)):>4} | "
          f"hit@1 {hits1 / n:.2f} | hit@3 {hits3 / n:.2f} | MRR@10 {rr / n:.2f} | hit@{BUDGET}ток {hits_budget / n:.2f} | разрезано {cut:>2} | "
          f"контекст top-3 {round(statistics.mean(ctx_tokens)):>4} ток. | длиннее окна {over} | разбиение {t_split:5.1f} с, эмбеддинги {t_embed:5.1f} с",
          flush=True)


print(f"корпус: {len(DOCS)} документов, {sum(len(t) for t in DOCS.values())} символов, "
      f"{sum(len(CL100K.encode(t)) for t in DOCS.values())} токенов cl100k; вопросов {len(QUESTIONS)}")
print("перекрытие везде size // 8; hit@k: эталонная подстрока целиком внутри одного из k найденных чанков")
print(f"hit@{BUDGET}ток: подстрока внутри первых {BUDGET} токенов склейки найденных чанков по рангу")
print()
qvecs = embed(["search_query: " + q["question"] for q in QUESTIONS])
for size in SIZES:
    for name, split in (("fixed", fixed), ("recursive", recursive), ("markdown", markdown), ("sentence", sentence)):
        evaluate(name, split, size, qvecs)
    print()
evaluate("semantic", semantic, 0, qvecs)
evaluate("whole", whole, 0, qvecs)
