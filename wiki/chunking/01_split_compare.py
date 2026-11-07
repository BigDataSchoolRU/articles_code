# langchain-text-splitters 1.1.3, llama-index-core 0.14.25, tiktoken 0.14.0, ollama 0.40.13 с nomic-embed-text, прогнано на стенде 2026-11-07
# Один документ режут разные сплиттеры: сколько чанков, какой длины и где проходит первая граница.
# Вторая часть показывает ловушку единиц: одинаковые chunk_size и chunk_overlap в символах и в токенах.
import inspect
import json
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

import tiktoken
from langchain_text_splitters import (
    CharacterTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
    TextSplitter,
    TokenTextSplitter,
)
from llama_index.core import constants as li_constants
from llama_index.core.node_parser import SentenceSplitter

HERE = Path(__file__).resolve().parent
OLLAMA = "http://localhost:11434"
DOC = (HERE / "corpus" / "vacation.md").read_text(encoding="utf-8")
CL100K = tiktoken.get_encoding("cl100k_base")  # тот же токенизатор, что у LlamaIndex по умолчанию
GPT2 = tiktoken.get_encoding("gpt2")  # умолчание from_tiktoken_encoder в LangChain


def tokens(text):
    return len(CL100K.encode(text))


def stats(name, chunks):
    chars = [len(c) for c in chunks]
    toks = [tokens(c) for c in chunks]
    print(
        f"{name:<44} чанков {len(chunks):>3} | символы мин/сред/макс "
        f"{min(chars):>4}/{round(statistics.mean(chars)):>4}/{max(chars):>4} | "
        f"токены cl100k {min(toks):>3}/{round(statistics.mean(toks)):>3}/{max(toks):>3}"
    )


def boundary(name, chunks):
    # конец первого чанка и начало второго: видно, режет ли сплиттер по смыслу или посреди слова
    end = chunks[0][-45:].replace("\n", "⏎")
    start = chunks[1][:45].replace("\n", "⏎")
    print(f"{name:<12} …{end} ‖ {start}…")


print("=== УМОЛЧАНИЯ УСТАНОВЛЕННЫХ ПАКЕТОВ ===")
sig = inspect.signature(TextSplitter.__init__).parameters
print("LangChain TextSplitter: chunk_size =", sig["chunk_size"].default,
      "| chunk_overlap =", sig["chunk_overlap"].default,
      "| length_function =", sig["length_function"].default.__name__, "(символы)")
print("LangChain from_tiktoken_encoder: encoding_name =",
      inspect.signature(TextSplitter.from_tiktoken_encoder).parameters["encoding_name"].default)
print("LangChain RecursiveCharacterTextSplitter: separators =", RecursiveCharacterTextSplitter()._separators)
ss = SentenceSplitter()
print("LlamaIndex SentenceSplitter: chunk_size =", ss.chunk_size, "| chunk_overlap =", ss.chunk_overlap, "(токены)")
print("LlamaIndex constants: DEFAULT_CHUNK_SIZE =", li_constants.DEFAULT_CHUNK_SIZE,
      "| DEFAULT_CHUNK_OVERLAP =", li_constants.DEFAULT_CHUNK_OVERLAP)

print()
print("=== ДОКУМЕНТ vacation.md В РАЗНЫХ ЕДИНИЦАХ ===")
print("символов", len(DOC), "| токенов cl100k", tokens(DOC), "| токенов gpt2", len(GPT2.encode(DOC)))

print()
print("=== ЛОВУШКА ЕДИНИЦ: chunk_size=256, chunk_overlap=32 ВЕЗДЕ ===")
by_chars = RecursiveCharacterTextSplitter(chunk_size=256, chunk_overlap=32).split_text(DOC)
by_cl100k = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", chunk_size=256, chunk_overlap=32).split_text(DOC)
by_gpt2 = RecursiveCharacterTextSplitter.from_tiktoken_encoder(chunk_size=256, chunk_overlap=32).split_text(DOC)
by_llama = SentenceSplitter(chunk_size=256, chunk_overlap=32).split_text(DOC)
stats("LangChain Recursive, len() = символы", by_chars)
stats("LangChain Recursive, токены cl100k", by_cl100k)
stats("LangChain Recursive, токены gpt2 (умолчание)", by_gpt2)
stats("LlamaIndex SentenceSplitter, токены cl100k", by_llama)

print()
print("=== ПЯТЬ СТРАТЕГИЙ НА ОДНОМ ДОКУМЕНТЕ, РАЗМЕР 128 ТОКЕНОВ cl100k, ПЕРЕКРЫТИЕ 16 ===")
fixed = TokenTextSplitter(encoding_name="cl100k_base", chunk_size=128, chunk_overlap=16).split_text(DOC)
character = CharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", separator="\n\n", chunk_size=128, chunk_overlap=16).split_text(DOC)
recursive = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base", chunk_size=128, chunk_overlap=16).split_text(DOC)
md_sections = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "doc"), ("##", "section")]).split_text(DOC)
sentence = SentenceSplitter(chunk_size=128, chunk_overlap=16).split_text(DOC)
stats("TokenTextSplitter (фиксированный размер)", fixed)
stats("CharacterTextSplitter по \\n\\n", character)
stats("RecursiveCharacterTextSplitter", recursive)
stats("MarkdownHeaderTextSplitter (# и ##)", [d.page_content for d in md_sections])
stats("LlamaIndex SentenceSplitter", sentence)

print()
print("=== ПЕРВАЯ ГРАНИЦА: КОНЕЦ ЧАНКА 1 ‖ НАЧАЛО ЧАНКА 2 ===")
boundary("fixed", fixed)
boundary("character", character)
boundary("recursive", recursive)
boundary("markdown", [d.page_content for d in md_sections])
boundary("sentence", sentence)
broken = sum(c.count("�") for c in fixed)
print("символов-заменителей U+FFFD в чанках TokenTextSplitter:", broken)


def mid_word_cuts(chunks):
    # граница посреди слова: последний символ чанка и следующий за ним в документе оба буквы или цифры;
    # U+FFFD в конце значит, что токен разрезал сам символ кириллицы (два байта UTF-8)
    cuts, example = 0, None
    for c in chunks[:-1]:
        if c.endswith("�"):
            cuts += 1
            example = example or c[-30:]
            continue
        start = DOC.find(c.lstrip("�").strip())
        end = start + len(c.lstrip("�").strip())
        if start >= 0 and end < len(DOC) and DOC[end - 1].isalnum() and DOC[end].isalnum():
            cuts += 1
            example = example or c[-30:]
    return cuts, example


for name, chunks in (("fixed", fixed), ("recursive", recursive), ("sentence", sentence)):
    cuts, example = mid_word_cuts(chunks)
    tail = f", пример конца чанка: …{example.replace(chr(10), '⏎')}" if example else ""
    print(f"{name:<10} границ посреди слова: {cuts} из {len(chunks) - 1}{tail}")

print()
print("=== МЕТАДАННЫЕ ЧАНКА ИЗ MarkdownHeaderTextSplitter ===")
for d in md_sections[2:4]:
    print(d.metadata, "|", d.page_content[:70].replace("\n", " "), "…")

print()
print("=== ОКНО МОДЕЛИ ЭМБЕДДИНГОВ nomic-embed-text ===")


def embed_raw(text, truncate):
    body = {"model": "nomic-embed-text", "input": [text], "truncate": truncate}
    req = urllib.request.Request(OLLAMA + "/api/embed", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}


whole = "search_document: " + "\n\n".join(p.read_text(encoding="utf-8") for p in sorted((HERE / "corpus").glob("*.md")))
print("весь корпус одной строкой: символов", len(whole), "| токенов cl100k", tokens(whole))
r = embed_raw(whole, truncate=False)
print("truncate=false:", r.get("error") or f"принято, prompt_eval_count {r.get('prompt_eval_count')}")
r = embed_raw(whole, truncate=True)
print("truncate=true (умолчание):", r.get("error") or f"принято без ошибки, prompt_eval_count {r.get('prompt_eval_count')}")
sys.exit(0)
