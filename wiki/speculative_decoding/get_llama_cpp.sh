#!/usr/bin/env bash
# llama.cpp v0.9.0 (сборка b12110 от 2026-11-04), CPU-релиз под Linux x86_64, прогнано на стенде 2026-11-12
# Скачивает готовый бинарный релиз llama.cpp, сверяет sha256 и распаковывает в ./llama.cpp рядом со скриптом.
set -euo pipefail
cd "$(dirname "$0")"

BUILD=b12110
ASSET=llama-${BUILD}-bin-ubuntu-x64.tar.gz
SHA256=368227edcc229be5f9bed16a2223d79b5e41d0ac2e19bcf5825e82291c060e55
URL=https://github.com/ggml-org/llama.cpp/releases/download/${BUILD}/${ASSET}

if [ -x llama.cpp/llama-server ]; then
  echo "llama.cpp уже распакован:"; llama.cpp/llama-server --version 2>&1 | tail -n 2; exit 0
fi

# Скачиваем архив и проверяем контрольную сумму, опубликованную в релизе на GitHub
curl -fL --retry 3 -o "$ASSET" "$URL"
echo "${SHA256}  ${ASSET}" | sha256sum -c -

# В архиве каталог с бинарниками и разделяемыми библиотеками, складываем его в ./llama.cpp
mkdir -p llama.cpp
tar -xzf "$ASSET" -C llama.cpp --strip-components=1
rm -f "$ASSET"
llama.cpp/llama-server --version 2>&1 | tail -n 2
