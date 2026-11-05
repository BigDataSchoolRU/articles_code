-- скрипт pgbench, postgres 18.6, прогнано на стенде 2026-11-05: одна короткая транзакция на коммит
INSERT INTO bench_commits (payload) VALUES (md5(random()::text));
