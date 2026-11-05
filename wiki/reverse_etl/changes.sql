-- postgres 18.6, прогнано на стенде 2026-11-05: изменения витрины между двумя прогонами синхронизации

-- два реальных изменения
UPDATE analytics.customer_scores SET ltv = 9999.00     WHERE customer_id = 7;
UPDATE analytics.customer_scores SET churn_risk = 'high' WHERE customer_id = 12;
-- UPDATE без смены значений: журнал БД его увидит, а diff результатов запроса нет
UPDATE analytics.customer_scores SET plan = plan        WHERE customer_id = 5;
-- новый клиент и ушедший клиент
INSERT INTO analytics.customer_scores VALUES (26, 'client26@example.com', 'team', 4200.50, 'low');
DELETE FROM analytics.customer_scores WHERE customer_id = 3;
