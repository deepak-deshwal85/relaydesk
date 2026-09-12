-- RelayDesk PostgreSQL schema (idempotent).
-- Run manually after RDS/database exists — not during API container startup.
-- Usage: python infra/scripts/bootstrap_db.py --yes

CREATE TABLE IF NOT EXISTS clients (
    id SERIAL PRIMARY KEY,
    client_phone_number VARCHAR(32),
    client_business_phone_number VARCHAR(32) UNIQUE,
    client_name VARCHAR(255) NOT NULL DEFAULT '',
    client_email_id VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS consumers (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    consumer_phone_number VARCHAR(32) NOT NULL,
    consumer_email_id VARCHAR(255) NOT NULL,
    consumer_name VARCHAR(255) NOT NULL DEFAULT '',
    consumer_address TEXT NOT NULL DEFAULT '',
    is_approved BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'READY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE consumers
    ADD COLUMN IF NOT EXISTS consumer_name VARCHAR(255) NOT NULL DEFAULT '';

ALTER TABLE consumers
    ADD COLUMN IF NOT EXISTS consumer_address TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_consumers_client_consumer
    ON consumers (client_id, consumer_phone_number);

CREATE INDEX IF NOT EXISTS idx_consumers_client_id
    ON consumers (client_id);

ALTER TABLE consumers
    DROP CONSTRAINT IF EXISTS chk_consumers_status;

ALTER TABLE consumers
    ADD CONSTRAINT chk_consumers_status
    CHECK (status IN ('READY', 'MEETING_SCHEDULED', 'MEETING_NOT_SCHEDULED'));

CREATE TABLE IF NOT EXISTS call_jobs (
    id UUID PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    status VARCHAR(32) NOT NULL,
    total_consumers INTEGER NOT NULL DEFAULT 0,
    calls_completed INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    results_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Older local databases stored phone/email on the job instead of client_id.
ALTER TABLE call_jobs
    ADD COLUMN IF NOT EXISTS client_id INTEGER REFERENCES clients(id) ON DELETE RESTRICT;

ALTER TABLE call_jobs
    ADD COLUMN IF NOT EXISTS total_consumers INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_call_jobs_client_id
    ON call_jobs (client_id);

CREATE INDEX IF NOT EXISTS idx_call_jobs_status
    ON call_jobs (status);

CREATE TABLE IF NOT EXISTS call_summaries (
    id SERIAL PRIMARY KEY,
    consumer_id INTEGER NOT NULL REFERENCES consumers(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    call_start_time TIMESTAMPTZ NOT NULL,
    call_end_time TIMESTAMPTZ,
    call_summary TEXT NOT NULL DEFAULT '',
    job_id UUID REFERENCES call_jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_summaries_consumer
    ON call_summaries (consumer_id);

CREATE INDEX IF NOT EXISTS idx_call_summaries_client_id
    ON call_summaries (client_id);

CREATE INDEX IF NOT EXISTS idx_call_summaries_client_start
    ON call_summaries (client_id, call_start_time DESC);

CREATE TABLE IF NOT EXISTS client_voice_agent_configs (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL UNIQUE REFERENCES clients(id) ON DELETE CASCADE,
    voice_agent_language VARCHAR(16) NOT NULL DEFAULT 'hi-IN',
    voice_agent_greeting_message TEXT NOT NULL DEFAULT (
        'Greet the caller briefly. Introduce the business and summarize key service '
        'offerings. Say you can answer questions by searching the uploaded documents. '
        'Ask what they would like to know.'
    ),
    calcom_username VARCHAR(255),
    calcom_event_type_slug VARCHAR(255),
    calcom_event_type_id INTEGER,
    calcom_organization_slug VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE client_voice_agent_configs
    ADD COLUMN IF NOT EXISTS voice_agent_language VARCHAR(16) NOT NULL DEFAULT 'hi-IN';

CREATE INDEX IF NOT EXISTS idx_client_voice_agent_configs_client_id
    ON client_voice_agent_configs (client_id);

CREATE TABLE IF NOT EXISTS client_voice_agent_schedules (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL UNIQUE REFERENCES clients(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    run_time VARCHAR(5) NOT NULL DEFAULT '09:00',
    days_of_week VARCHAR(32) NOT NULL DEFAULT '1,2,3,4,5',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_job_id UUID REFERENCES call_jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_voice_agent_schedules_next_run
    ON client_voice_agent_schedules (next_run_at)
    WHERE enabled = TRUE;

-- Per-client Plivo number plus the LiveKit trunks used to call from that number.
CREATE TABLE IF NOT EXISTS client_phone_lines (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL UNIQUE REFERENCES clients(id) ON DELETE CASCADE,
    provider VARCHAR(32) NOT NULL DEFAULT 'plivo',
    status VARCHAR(32) NOT NULL DEFAULT 'provisioning',
    country_iso VARCHAR(2) NOT NULL DEFAULT 'IN',
    phone_number VARCHAR(32),
    phone_number_e164 VARCHAR(32),
    plivo_origination_uri_uuid VARCHAR(64),
    plivo_inbound_trunk_id VARCHAR(64),
    plivo_credential_uuid VARCHAR(64),
    plivo_outbound_trunk_id VARCHAR(64),
    plivo_outbound_domain VARCHAR(255),
    sip_username VARCHAR(32),
    sip_password VARCHAR(64),
    livekit_inbound_trunk_id VARCHAR(64),
    livekit_outbound_trunk_id VARCHAR(64),
    livekit_dispatch_rule_id VARCHAR(64),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_client_phone_lines_phone
    ON client_phone_lines (phone_number)
    WHERE phone_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_client_phone_lines_client_id
    ON client_phone_lines (client_id);
