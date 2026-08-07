# Мультимодальность: картинки, аудио, видео

Код к статье «Мультимодальность: картинки, аудио, видео» на сайте BigDataSchool: https://bigdataschool.ru/blog/news/openrouter-multimodality-image-audio-video/

## Состав
- `detect_modalities.py` - обнаружение возможностей моделей по каталогу `/models`.
- `image_generate.py` - генерация картинки через chat с `modalities`.
- `speech_synthesize.py` - синтез речи стримом PCM16 в WAV.
- `audio_transcribe.py` - распознавание речи через `/audio/transcriptions`.
- `video_generate.py` - асинхронная генерация видео: submit, поллинг, ссылка на результат. Платный вызов.
- `RUNBOOK.md` - пошаговый прогон с проверками.

## Окружение
Python 3.12, пакет `httpx`. Ключ OpenRouter в переменной окружения `OPENROUTER_API_KEY`.

## Как запустить
1. Установить зависимости: `pip install httpx`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить файлы по очереди: `detect_modalities.py`, `image_generate.py`, `speech_synthesize.py`, `audio_transcribe.py` (использует файл, созданный предыдущим шагом), `video_generate.py` (платный, генерация видео стоит реальные деньги).
