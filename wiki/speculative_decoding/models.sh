#!/usr/bin/env bash
# Ollama 0.40.13, модели qwen2.5:7b (Q4_K_M) и qwen2.5:0.5b-instruct-q8_0, прогнано на стенде 2026-11-12
# Находит GGUF-файлы моделей в хранилище Ollama и ставит на них симлинки в ./models.
# Ollama хранит веса как blob с именем sha256-<хэш>, а сам blob это обычный GGUF, который читает llama.cpp.
# Использование: ./models.sh [каталог моделей Ollama ...], по умолчанию $OLLAMA_MODELS или ~/.ollama/models.
# Каталогов можно передать несколько: манифест модели ищется в каждом по очереди.
set -euo pipefail
cd "$(dirname "$0")"

if [ $# -gt 0 ]; then DIRS=("$@"); else DIRS=("${OLLAMA_MODELS:-$HOME/.ollama/models}"); fi
mkdir -p models

link() {  # link <модель:тег> <имя симлинка>
  local name=${1%%:*} tag=${1#*:}
  local dir manifest=""
  for dir in "${DIRS[@]}"; do
    [ -f "$dir/manifests/registry.ollama.ai/library/$name/$tag" ] && { manifest="$dir/manifests/registry.ollama.ai/library/$name/$tag"; break; }
  done
  [ -n "$manifest" ] || { echo "нет манифеста $1 в ${DIRS[*]}: сделайте ollama pull $1" >&2; return 1; }
  # В манифесте ищем слой с весами модели (mediaType ...image.model)
  local digest
  digest=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(next(l["digest"] for l in m["layers"] if l["mediaType"].endswith(".model")))' "$manifest")
  local blob="$dir/blobs/${digest/:/-}"
  # Первые 4 байта GGUF-файла это магия "GGUF"
  [ "$(head -c 4 "$blob")" = "GGUF" ] || { echo "$blob не GGUF" >&2; return 1; }
  ln -sfn "$blob" "models/$2"
  echo "models/$2 -> $blob ($(stat -L -c %s "models/$2") байт)"
}

link qwen2.5:7b                   qwen2.5_7b_instruct_q4_k_m.gguf
link qwen2.5:0.5b-instruct-q8_0   qwen2.5_0.5b_instruct_q8_0.gguf
