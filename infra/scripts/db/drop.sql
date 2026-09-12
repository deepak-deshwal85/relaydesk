-- Drop all RelayDesk application tables (destructive).
-- Order respects foreign keys.

DROP TABLE IF EXISTS client_phone_lines CASCADE;
DROP TABLE IF EXISTS call_summaries CASCADE;
DROP TABLE IF EXISTS call_jobs CASCADE;
DROP TABLE IF EXISTS client_voice_agent_schedules CASCADE;
DROP TABLE IF EXISTS client_voice_agent_configs CASCADE;
DROP TABLE IF EXISTS consumers CASCADE;
DROP TABLE IF EXISTS clients CASCADE;
