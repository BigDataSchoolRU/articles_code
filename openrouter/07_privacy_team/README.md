# Приватность, безопасность и работа командой

Код к статье «Приватность, безопасность и работа командой» на сайте BigDataSchool: https://bigdataschool.ru/blog/news/openrouter-privacy-byok-team/

## Состав
- `privacy_routing.py` - маршрутизация только через провайдеров без хранения данных (`data_collection: deny`).
- `key_usage.py` - контроль расхода по ключу через `/auth/key`.
- `scoped_key.py` - шаблон запроса на выпуск ключа с лимитом и IP-allowlist через Provisioning API. Требует отдельный management-ключ, без него эндпоинт отвечает 401.
- `RUNBOOK.md` - пошаговый прогон с проверками.

## Окружение
Python 3.12, пакет `httpx`. Ключ инференса OpenRouter в переменной окружения `OPENROUTER_API_KEY`. Для `scoped_key.py` нужен отдельный management-ключ в `OPENROUTER_PROVISIONING_KEY`.

## Как запустить
1. Установить зависимости: `pip install httpx`.
2. Экспортировать ключ: `export OPENROUTER_API_KEY="sk-or-v1-ваш_ключ"`.
3. Запустить `python3 privacy_routing.py` и `python3 key_usage.py`.
4. Для `scoped_key.py` дополнительно экспортировать `OPENROUTER_PROVISIONING_KEY` с management-ключом.
