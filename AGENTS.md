# AGENTS.md — articles_code

Публичный репо демо-кода к статьям. Правила написания демо живут в плагине bds-wiki, стадия
`wiki-code` (`bds-prompts/system-prompts/plugins/bds-wiki/skills/wiki-code/rules.md`). Здесь только то,
что касается репо.

## Гейт

```sh
ops/selfcheck.sh
```

## Правила

- Новое демо — `wiki/<slug>/` с `README.md` (название, canonical URL статьи, состав файлов, запуск) и
  `RUNBOOK.md`, плюс строка в `wiki/README.md`. `ops/selfcheck.sh` проверяет все три условия.
- Первая строка каждого файла кода — комментарий с пином версий (правило wiki-code).
- Не коммитятся: `selfcheck.sh`, `.status`, `run_output.txt`, `__pycache__`, venv, `.env`, ключи и
  токены. Репо публичный: всё, что попало в git, видно всем, даже после удаления.
- Опубликованный код не переименовывается и не переносится: на него ведут ссылки со статей
  (`docs/adr/0001-light-standard.md`). Правка кода статьи делается вместе с правкой самой статьи.
