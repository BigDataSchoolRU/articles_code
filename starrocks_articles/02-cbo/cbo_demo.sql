-- Код к статье "Cost-Based Optimizer в StarRocks: как оптимизатор строит план"
-- из серии материалов по StarRocks, "Школа Больших Данных".
-- Полный текст статьи: https://bigdataschool.ru/blog/news/starrocks-cost-based-optimizer/
-- Автор: Bigdataschool.ru   "Школа Больших Данных"
-- Онлайн-курс по StarRocks: https://bigdataschool.ru/courses/starrocks_online_datawarehouse_htap/
--
-- ============================================================
-- cbo_demo.sql
-- Демонстрация Cost-Based Optimizer в StarRocks на стенде shop.
-- Показываем, как ANALYZE меняет план: до сбора статистики один
-- порядок соединений, после сбора другой.
-- Проверено под StarRocks 3.5.0. Синтаксис свериться на стенде командой
-- SHOW STATS META до и после сброса, это индикатор, что шаги сработали.
--
-- Запуск целиком не рекомендуется. Идём по шагам, снимая планы между ними.
-- ============================================================

USE shop;

-- ------------------------------------------------------------
-- ШАГ 1. Подготовка. Сбрасываем статистику и глушим автосбор.
-- Без отключения автосбора статистика вернётся сама через минуту,
-- и состояние "до" не покажешь.
-- ------------------------------------------------------------

-- 1.1 Отключаем автоматический сбор статистики на время демо
ADMIN SET FRONTEND CONFIG ("enable_statistic_collect" = "false");

-- 1.2 Удаляем собранную базовую статистику по таблицам сценария
DROP STATS orders;
DROP STATS order_items;
DROP STATS customers;

-- 1.3 Если по колонкам создавались гистограммы, снять и их.
--     По умолчанию автосбор гистограммы не строит, поэтому строки ниже
--     нужны только если ты собирал их вручную. Если гистограмм нет,
--     StarRocks ответит, что удалять нечего, это не ошибка сценария.
-- ANALYZE TABLE orders DROP HISTOGRAM ON order_date, status;

-- 1.4 Проверяем, что статистики больше нет. По этим таблицам вывод пуст.
SHOW STATS META;
SHOW HISTOGRAM META;

-- ------------------------------------------------------------
-- ШАГ 2. План ДО статистики.
-- Берём компактный запрос на три таблицы (два JOIN), чтобы план
-- помещался на экран. Селективный фильтр по orders это ключ к демо.
-- ------------------------------------------------------------

-- 2.1 Компактный план, видно порядок соединений.
EXPLAIN
SELECT c.region_id, count(*) AS cnt
FROM order_items oi
JOIN orders o    ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_date >= '2025-04-01' AND o.status = 'paid'
GROUP BY c.region_id;

-- 2.2 Из вывода COSTS берём оценку строк (row:) по узлам SCAN orders
--     и по HASH JOIN. Без статистики оценка селективности фильтра
--     грубая, это состояние "до".
EXPLAIN COSTS
SELECT c.region_id, count(*) AS cnt
FROM order_items oi
JOIN orders o    ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_date >= '2025-04-01' AND o.status = 'paid'
GROUP BY c.region_id;

-- ------------------------------------------------------------
-- ШАГ 3. Собираем статистику вручную.
-- ANALYZE TABLE это полный синхронный сбор по таблице.
-- ------------------------------------------------------------

ANALYZE TABLE orders;
ANALYZE TABLE order_items;
ANALYZE TABLE customers;

-- Гистограммы по колонкам фильтра дают ещё более точную селективность.
-- Для наглядного сдвига плана можно добавить их по orders.
ANALYZE TABLE orders UPDATE HISTOGRAM ON order_date, status;

-- Проверяем, что статистика появилась.
SHOW STATS META;

-- ------------------------------------------------------------
-- ШАГ 4. План ПОСЛЕ статистики.
-- Тот же запрос. Оптимизатор видит реальную кардинальность orders
-- после фильтра (около 9.19 млн из 160 млн) и меняет порядок JOIN,
-- ставя маленькую сторону в build.
-- ------------------------------------------------------------

-- 4.1 Компактный план. Сравниваем порядок соединений с планом из шага 2.
EXPLAIN
SELECT c.region_id, count(*) AS cnt
FROM order_items oi
JOIN orders o    ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_date >= '2025-04-01' AND o.status = 'paid'
GROUP BY c.region_id;

-- 4.2 Берём те же оценки row: по SCAN orders и HASH JOIN.
--     Теперь, со статистикой, оценка селективности точная (состояние "после").
EXPLAIN COSTS
SELECT c.region_id, count(*) AS cnt
FROM order_items oi
JOIN orders o    ON oi.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_date >= '2025-04-01' AND o.status = 'paid'
GROUP BY c.region_id;

-- ------------------------------------------------------------
-- ШАГ 5. Возвращаем стенд в рабочее состояние.
-- Включаем автосбор обратно, чтобы дальше база жила нормально.
-- ------------------------------------------------------------

ADMIN SET FRONTEND CONFIG ("enable_statistic_collect" = "true");
