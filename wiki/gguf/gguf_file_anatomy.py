# gguf 0.19.0, Ollama 0.40.13, модель qwen2.5:0.5b-instruct-q4_0, прогнано на стенде 2026-11-03
"""Что лежит внутри GGUF-файла: заголовок, метаданные и описания тензоров.

Файл берётся прямо из локального хранилища Ollama: модель, скачанная
командой `ollama pull`, лежит там обычным GGUF-файлом под именем-хешем.
"""
import json
import os
import struct
import sys
import time
from pathlib import Path

import gguf

TAG = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:0.5b-instruct-q4_0"
# каталог моделей Ollama: переменная OLLAMA_MODELS или путь по умолчанию
MODELS_DIR = Path(os.environ.get("OLLAMA_MODELS", Path.home() / ".ollama" / "models"))


def find_gguf_blob(tag: str) -> Path:
    """Путь к GGUF-файлу тега: манифест Ollama перечисляет слои модели."""
    name, _, version = tag.partition(":")
    manifest = (MODELS_DIR / "manifests" / "registry.ollama.ai" / "library"
                / name / (version or "latest"))
    layers = json.loads(manifest.read_text())["layers"]
    # веса модели лежат в слое image.model, остальное это шаблон, лицензия, параметры
    digest = next(l["digest"] for l in layers
                  if l["mediaType"] == "application/vnd.ollama.image.model")
    return MODELS_DIR / "blobs" / digest.replace(":", "-")


path = find_gguf_blob(TAG)
print(f"Модель: {TAG}")
print(f"Файл:   {path.name}  ({path.stat().st_size / 2**20:.1f} МиБ)")

# 1. Заголовок читается без всяких библиотек: 4 байта magic, uint32 версии,
#    два uint64 счётчика. Порядок байтов little-endian.
with open(path, "rb") as f:
    magic, version, n_tensors, n_kv = struct.unpack("<4sIQQ", f.read(24))
print("\n=== Заголовок (первые 24 байта) ===")
print(f"magic={magic!r} version={version} tensor_count={n_tensors} metadata_kv_count={n_kv}")

# 2. Тот же файл через официальный пакет gguf из репозитория llama.cpp
t = time.perf_counter()
reader = gguf.GGUFReader(path)
print(f"\nGGUFReader открыл файл за {time.perf_counter() - t:.2f} с")

print("\n=== Метаданные ключ-значение ===")
for key, field in reader.fields.items():
    if key.startswith("GGUF."):  # служебные поля заголовка, уже показаны выше
        continue
    vtype = field.types[0].name
    if field.types[0] == gguf.GGUFValueType.ARRAY:
        # массивы токенизатора огромные, печатаем только тип и длину
        print(f"{key:42} ARRAY[{field.types[-1].name}] x {len(field.data)}")
    elif key == "tokenizer.chat_template":
        print(f"{key:42} STRING, {len(field.contents())} символов шаблона Jinja")
    else:
        print(f"{key:42} {vtype:8} {field.contents()}")

# general.file_type хранит число, имя типа даёт перечисление LlamaFileType
file_type = reader.fields["general.file_type"].contents()
print(f"\ngeneral.file_type = {file_type} -> {gguf.LlamaFileType(file_type).name}")

# 3. Описания тензоров: имя, форма (в порядке ggml, первым идёт ne0),
#    тип квантования и смещение начала тензора от начала файла
print("\n=== Описания тензоров (первые 6 из", len(reader.tensors), ") ===")
for tensor in reader.tensors[:6]:
    print(f"{tensor.name:28} shape={str([int(d) for d in tensor.shape]):14} "
          f"type={tensor.tensor_type.name:5} offset={tensor.data_offset}")

# 4. Выравнивание: начало каждого тензора кратно general.alignment,
#    поэтому веса можно отобразить в память через mmap без копирования
alignment = reader.alignment
first = min(t.data_offset for t in reader.tensors)
aligned = sum(t.data_offset % alignment == 0 for t in reader.tensors)
print(f"\nВыравнивание: {alignment} байт (ключа general.alignment в файле "
      f"{'нет, взято значение по умолчанию' if 'general.alignment' not in reader.fields else 'есть'})")
print(f"Блок данных начинается со смещения {first} байт "
      f"({first / 2**20:.1f} МиБ ушло на заголовок, метаданные и описания тензоров)")
print(f"Тензоров с выровненным началом: {aligned} из {len(reader.tensors)}")
