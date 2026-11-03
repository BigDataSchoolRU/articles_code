# RUNBOOK: разбор GGUF-файла модели из Ollama

## Окружение

| Что | Версия |
|---|---|
| Python | 3.12 |
| `gguf` (PyPI) | 0.19.0, тянет `numpy` |
| Ollama | 0.40.13, локальная установка или Docker |
| Модели | `qwen2.5:0.5b-instruct-q4_0` (352 МБ), `qwen2.5:0.5b-instruct-q8_0` (531 МБ) |

Нужно около 900 МБ на диске и около 600 МБ свободной памяти: на прогоне пик памяти процесса
`gguf_file_anatomy.py` был 524 МиБ. Веса `GGUFReader` отображает в память через mmap и не
читает целиком, а словарь токенизатора разбирает в Python-объекты. GPU не нужен, модель не
запускается.

## Шаг 1. Ollama и модели

Если Ollama стоит локально:

```bash
ollama pull qwen2.5:0.5b-instruct-q4_0
ollama pull qwen2.5:0.5b-instruct-q8_0
ollama list
```

Если Ollama нет, её можно поднять в Docker из этой папки. Каталог моделей контейнера
смонтирован в `./ollama` рядом с кодом, поэтому файлы видны с хоста:

```bash
docker compose up -d
docker exec gguf-ollama ollama pull qwen2.5:0.5b-instruct-q4_0
docker exec gguf-ollama ollama pull qwen2.5:0.5b-instruct-q8_0
docker exec gguf-ollama ollama list
```

Шаг прошёл, если в списке есть обе модели:

```
NAME                          ID              SIZE      MODIFIED
qwen2.5:0.5b-instruct-q8_0    84d044692a2c    531 MB    ...
qwen2.5:0.5b-instruct-q4_0    44deb286b008    352 MB    ...
```

## Шаг 2. Где Ollama хранит модели

Скрипты ищут модели в `$OLLAMA_MODELS`, а без переменной в `~/.ollama/models`. Подставьте свой
путь:

| Установка | Каталог моделей |
|---|---|
| macOS, Windows, Linux от своего пользователя | `~/.ollama/models` |
| Linux через официальный `install.sh` (служба systemd) | `/usr/share/ollama/.ollama/models` |
| Docker из этой папки | `./ollama/models` |

```bash
export OLLAMA_MODELS=./ollama/models   # пример для Docker
ls $OLLAMA_MODELS/manifests/registry.ollama.ai/library/qwen2.5/
```

В выводе должны быть два файла манифеста: `0.5b-instruct-q4_0` и `0.5b-instruct-q8_0`.

## Шаг 3. Пакет gguf

```bash
python3 -m venv .venv
.venv/bin/pip install gguf==0.19.0
.venv/bin/python -c "import gguf; print(gguf.GGUF_VERSION, gguf.GGUF_DEFAULT_ALIGNMENT)"
```

Должно напечататься `3 32`: текущая версия формата и выравнивание по умолчанию.

## Шаг 4. Устройство файла

```bash
.venv/bin/python gguf_file_anatomy.py qwen2.5:0.5b-instruct-q4_0
```

Скрипт находит GGUF-файл через манифест Ollama, читает первые 24 байта без библиотек и затем
открывает файл через `gguf.GGUFReader`. Ожидаемый вывод (сокращён):

```
=== Заголовок (первые 24 байта) ===
magic=b'GGUF' version=3 tensor_count=290 metadata_kv_count=34

GGUFReader открыл файл за 9.40 с

=== Метаданные ключ-значение ===
general.architecture                       STRING   qwen2
...
qwen2.block_count                          UINT32   24
qwen2.context_length                       UINT32   32768
...
tokenizer.ggml.tokens                      ARRAY[STRING] x 151936
...
general.file_type = 2 -> MOSTLY_Q4_0

=== Описания тензоров (первые 6 из 290 ) ===
token_embd.weight            shape=[896, 151936]  type=Q8_0  offset=5948224
blk.0.attn_norm.weight       shape=[896]          type=F32   offset=150591296
...
Выравнивание: 32 байт (ключа general.alignment в файле нет, взято значение по умолчанию)
Блок данных начинается со смещения 5948224 байт (5.7 МиБ ушло на заголовок, метаданные и описания тензоров)
Тензоров с выровненным началом: 290 из 290
```

Шаг прошёл, если magic равен `b'GGUF'`, а все тензоры выровнены. Время открытия зависит от
машины: почти всё оно уходит на разбор словаря токенизатора, а не на веса.

## Шаг 5. Смесь типов квантования

```bash
.venv/bin/python gguf_quant_mix.py qwen2.5:0.5b-instruct-q4_0 qwen2.5:0.5b-instruct-q8_0
```

Ожидаемый вывод:

```
=== qwen2.5:0.5b-instruct-q4_0 ===
размер файла 335.8 МиБ, general.file_type = MOSTLY_Q4_0
тип    тензоров  весов, млн  доля весов  бит на вес
Q4_0        168       357.8      72.43%        4.50
Q8_0          1       136.1      27.56%        8.50
F32         121         0.1       0.01%       32.00
итого: 494.0 млн весов, в среднем 5.61 бит на вес
не в Q4_0: 122 тензоров, виды: attn_k.bias, attn_norm.weight, attn_q.bias, attn_v.bias, ffn_norm.weight, output_norm.weight, token_embd.weight

=== qwen2.5:0.5b-instruct-q8_0 ===
размер файла 506.5 МиБ, general.file_type = MOSTLY_Q8_0
тип    тензоров  весов, млн  доля весов  бит на вес
Q8_0        169       494.0      99.99%        8.50
F32         121         0.1       0.01%       32.00
итого: 494.0 млн весов, в среднем 8.50 бит на вес
не в Q8_0: 121 тензоров, виды: attn_k.bias, attn_norm.weight, attn_q.bias, attn_v.bias, ffn_norm.weight, output_norm.weight
```

Q4_0 хранит блоки по 32 веса: 16 байт 4-битных значений плюс масштаб в fp16, отсюда 4,5 бита
на вес. Q8_0 устроен так же с 8-битными значениями, отсюда 8,5.

## Если не так

- **`FileNotFoundError` на манифесте.** Скрипт смотрит не в тот каталог. Проверьте
  `OLLAMA_MODELS` по таблице из шага 2 и что тег написан полностью, с двоеточием.
- **`PermissionError` на blob.** У службы Ollama на Linux и у Docker файлы принадлежат другому
  пользователю. Обычно они читаемы всем (`-rw-r--r--`). Если нет, дайте права на чтение или
  запустите скрипт от того же пользователя.
- **`StopIteration` в `find_gguf_blob`.** В манифесте тега нет слоя
  `application/vnd.ollama.image.model`, то есть локальных весов. Проверьте манифест из шага 2
  и возьмите тег, который `ollama list` показывает с размером.
- **Другие числа в выводе.** Если в библиотеке Ollama перезалили тег, у файла будет другой хеш
  и, возможно, другой состав тензоров. Сверяйте ID из `ollama list` с шагом 1.
- **Открытие идёт десятки секунд или падает по памяти.** Мало свободной памяти. Словарь в
  151 936 токенов `GGUFReader` разбирает целиком при открытии файла, на прогоне это около
  9 секунд и 524 МиБ.
