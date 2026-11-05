-- postgres 18.6 в Docker, прогнано на стенде 2026-11-05
-- Durability: что пережило аварийную остановку.
SELECT id, note FROM orders ORDER BY id;
SELECT count(*) FILTER (WHERE note LIKE 'подтверждён%') AS committed_survived,
       count(*) FILTER (WHERE note = 'не зафиксирован')  AS uncommitted_survived
FROM orders;
