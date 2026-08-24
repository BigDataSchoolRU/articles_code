# Мультимодальный ИИ (Multimodal AI)

Код к Wiki-статье «Мультимодальный ИИ (Multimodal AI)» на сайте BigDataSchool: https://bigdataschool.ru/wiki/multimodal_ai/

## Состав
- `make_sample.py` — рисует тестовую таблицу продаж и отдаёт её же текстом
- `image_to_tokens.py` — одна картинка в трёх разрешениях, замер токенов промпта
- `text_vs_image.py` — одинаковый вопрос картинкой и текстом на одной модели
- `RUNBOOK.md` — пошаговый прогон с проверками

## Окружение
Python 3.12, Ollama 0.32.13, модель qwen2.5vl:7b (около 6 ГБ), пакеты ollama 0.6.2 и pillow 12.3.0.

## Как запустить
1. `ollama pull qwen2.5vl:7b`
2. `python3 -m pip install "ollama==0.6.2" "pillow==12.3.0"`
3. `python3 image_to_tokens.py`
4. `python3 text_vs_image.py`
