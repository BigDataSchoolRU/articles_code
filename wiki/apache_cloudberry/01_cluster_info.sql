-- Apache Cloudberry 2.2.0-incubating, демо-кластер gpdemo (координатор, standby, 3 primary, 3 mirror на одном хосте), прогнано на стенде 2026-11-15
-- Из чего собран кластер: версия ядра и список экземпляров Postgres.

-- Cloudberry сообщает и версию ядра PostgreSQL, и свою версию.
SELECT version();

-- Каждая строка gp_segment_configuration это отдельный экземпляр Postgres со своим портом и каталогом.
-- content = -1: координатор и standby-координатор; content 0..N-1: сегменты.
-- role p/m: primary или mirror сейчас; preferred_role: роль по замыслу; mode s: зеркало синхронизировано; status u: экземпляр работает.
SELECT content, role, preferred_role, mode, status, port
FROM gp_segment_configuration
ORDER BY content, role DESC;

-- Параллельность запроса определяют primary-сегменты: на каждом выполняется своя часть плана.
SELECT count(*) AS primary_segments
FROM gp_segment_configuration
WHERE content >= 0 AND role = 'p';

-- Оптимизатор по умолчанию (on = GPORCA) и транспорт interconnect между сегментами.
SHOW optimizer;
SHOW gp_interconnect_type;
