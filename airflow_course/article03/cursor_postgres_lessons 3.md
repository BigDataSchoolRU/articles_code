# Создание таблицы Postgres с полями даты
_Exported on 1/31/2026 at 12:29:35 GMT-3 from Cursor (2.4.21)_

---

**User**

@\home\ubuntu\.cursor\projects\1769728302424\terminals\1.txt:18-31 "Напиши SQL-запрос CREATE TABLE для Postgres, который соответствует этой структуре данных. Добавь поля created_at и updated_at."

---

**Cursor**


Вот вариант `CREATE TABLE` с полями `created_at` и `updated_at`:

```sql
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50),
    signup_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**Что добавлено:**

- **`created_at`** — момент создания строки, по умолчанию текущее время.
- **`updated_at`** — момент последнего изменения; в таком виде при вставке совпадает с `created_at`, при ручном `UPDATE` его нужно обновлять самому, например:  
  `UPDATE users SET name = 'Bob', updated_at = CURRENT_TIMESTAMP WHERE id = 1;`

**Почему `TIMESTAMPTZ`:** хранит время в UTC и конвертирует в часовой пояс сессии при выборке, для логов и аудита обычно удобнее, чем `TIMESTAMP` без зоны.

Если нужна автоматическая подстановка `updated_at` при любом `UPDATE`, это делается триггером в Postgres — могу написать пример триггера отдельно.

