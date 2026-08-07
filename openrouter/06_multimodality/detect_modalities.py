# протестировано на EU-ноде (AWS Stockholm) 2026-08-04: Python 3.12.3, httpx 0.28.1, OpenRouter API
# Обнаружение возможностей: какие модели умеют картинки, аудио на вход и аудио на выход.
import os
import httpx

# Ключ читаем из окружения, в код не вписываем.
key = os.environ["OPENROUTER_API_KEY"]

# Эндпоинт /models отдаёт весь каталог. У каждой модели в architecture есть
# input_modalities и output_modalities, по ним и определяем возможности.
models = httpx.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {key}"},
    timeout=60,
).json()["data"]

def out(x, mod):
    # True, если модель выдаёт указанную модальность на выход.
    return mod in (x.get("architecture", {}).get("output_modalities") or [])

def inp(x, mod):
    # True, если модель принимает указанную модальность на вход.
    return mod in (x.get("architecture", {}).get("input_modalities") or [])

# Фильтруем каталог по нужным модальностям.
images = [x["id"] for x in models if out(x, "image")]       # генерация картинок
audio_in = [x["id"] for x in models if inp(x, "audio")]     # распознавание и понимание речи
audio_out = [x["id"] for x in models if out(x, "audio")]    # синтез речи

# Печатаем счётчики и по пять примеров на каждую группу.
print("картинки на выход:", len(images))
for i in images[:5]:
    print("  ", i)
print("аудио на вход (распознавание и понимание):", len(audio_in))
for i in audio_in[:5]:
    print("  ", i)
print("аудио на выход (синтез речи):", len(audio_out))
for i in audio_out[:5]:
    print("  ", i)
