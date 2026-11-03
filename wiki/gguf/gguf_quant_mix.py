# gguf 0.19.0, Ollama 0.40.13, модели qwen2.5:0.5b-instruct-q4_0 и q8_0, прогнано на стенде 2026-11-03
"""Из каких типов квантования на деле собран GGUF-файл.

Суффикс в имени (Q4_0, Q8_0, Q4_K_M) говорит о преобладающем типе, но
отдельные тензоры часто хранятся в другом. Скрипт считает это по факту.
"""
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import gguf

TAGS = sys.argv[1:] or ["qwen2.5:0.5b-instruct-q4_0", "qwen2.5:0.5b-instruct-q8_0"]
# каталог моделей Ollama: переменная OLLAMA_MODELS или путь по умолчанию
MODELS_DIR = Path(os.environ.get("OLLAMA_MODELS", Path.home() / ".ollama" / "models"))


def find_gguf_blob(tag: str) -> Path:
    """Путь к GGUF-файлу тега: манифест Ollama перечисляет слои модели."""
    name, _, version = tag.partition(":")
    manifest = (MODELS_DIR / "manifests" / "registry.ollama.ai" / "library"
                / name / (version or "latest"))
    layers = json.loads(manifest.read_text())["layers"]
    digest = next(l["digest"] for l in layers
                  if l["mediaType"] == "application/vnd.ollama.image.model")
    return MODELS_DIR / "blobs" / digest.replace(":", "-")


for tag in TAGS:
    path = find_gguf_blob(tag)
    reader = gguf.GGUFReader(path)
    file_type = gguf.LlamaFileType(reader.fields["general.file_type"].contents())

    # по каждому типу тензора: сколько тензоров, весов и байт на диске
    stats = defaultdict(lambda: [0, 0, 0])
    for t in reader.tensors:
        s = stats[t.tensor_type.name]
        s[0] += 1
        s[1] += int(t.n_elements)
        s[2] += int(t.n_bytes)

    total_w = sum(s[1] for s in stats.values())
    total_b = sum(s[2] for s in stats.values())
    print(f"\n=== {tag} ===")
    print(f"размер файла {path.stat().st_size / 2**20:.1f} МиБ, "
          f"general.file_type = {file_type.name}")
    print(f"{'тип':6} {'тензоров':>8} {'весов, млн':>11} {'доля весов':>11} {'бит на вес':>11}")
    for name, (n, w, b) in sorted(stats.items(), key=lambda kv: -kv[1][1]):
        print(f"{name:6} {n:8} {w / 1e6:11.1f} {w / total_w:11.2%} {8 * b / w:11.2f}")
    print(f"итого: {total_w / 1e6:.1f} млн весов, в среднем {8 * total_b / total_w:.2f} бит на вес")

    # какие тензоры хранятся не в «основном» типе файла
    main = max(stats, key=lambda k: stats[k][1])
    other = [t for t in reader.tensors if t.tensor_type.name != main]
    # имя вида blk.7.attn_q.bias сокращаем до attn_q.bias, номер слоя не важен
    kinds = sorted({t.name.split(".", 2)[2] if t.name.startswith("blk.") else t.name
                    for t in other})
    print(f"не в {main}: {len(other)} тензоров, виды: {', '.join(kinds)}")
