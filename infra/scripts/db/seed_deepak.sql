-- Seed data for Deepak dev/bootstrap environment.
-- Requires schema.sql applied first. Drops UNIQUE on business phone so two
-- client accounts can share one outbound line (911171366880).
-- Voice-agent resolve-by-phone picks the lowest client id when duplicates exist.

ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_client_business_phone_number_key;

INSERT INTO clients (
    client_phone_number,
    client_business_phone_number,
    client_name,
    client_email_id
) VALUES
    (
        '919876543210',
        '911171366880',
        'Deepak Deshwal (Gmail)',
        'deepakdeshwal85@gmail.com'
    ),
    (
        '919988776655',
        '911171366880',
        'Deepak Deshwal (Yahoo)',
        'deepakdeshwal85@yahoo.com'
    );

INSERT INTO consumers (
    client_id,
    consumer_phone_number,
    consumer_email_id,
    is_approved,
    status
)
SELECT
    c.id,
    v.consumer_phone_number,
    v.consumer_email_id,
    TRUE,
    v.status
FROM clients AS c
JOIN (
    VALUES
        ('deepakdeshwal85@gmail.com', '919868402577', 'alice@example.com', 'READY'),
        ('deepakdeshwal85@gmail.com', '918318589094', 'bob@example.com', 'READY'),
        ('deepakdeshwal85@yahoo.com', '919868402577', 'carol@example.com', 'READY'),
        ('deepakdeshwal85@yahoo.com', '918318589094', 'dave@example.com', 'MEETING_NOT_SCHEDULED')
) AS v(client_email_id, consumer_phone_number, consumer_email_id, status)
    ON c.client_email_id = v.client_email_id;

INSERT INTO call_jobs (
    id,
    client_id,
    status,
    total_consumers,
    calls_completed,
    started_at,
    completed_at,
    results_json
)
SELECT
    v.job_id::uuid,
    c.id,
    v.status,
    v.total_consumers,
    v.calls_completed,
    v.started_at,
    v.completed_at,
    v.results_json
FROM clients AS c
JOIN (
    VALUES
        (
            'deepakdeshwal85@gmail.com',
            'aaaaaaaa-bbbb-cccc-dddd-000000000001',
            'completed',
            2,
            2,
            NOW() - INTERVAL '1 day',
            NOW() - INTERVAL '1 day' + INTERVAL '10 minutes',
            '[{"consumer_id":1,"consumer_phone_number":"919900000001","success":true,"detail":"answered"},{"consumer_id":2,"consumer_phone_number":"919900000002","success":true,"detail":"answered"}]'
        ),
        (
            'deepakdeshwal85@yahoo.com',
            'aaaaaaaa-bbbb-cccc-dddd-000000000002',
            'pending',
            0,
            0,
            NULL::timestamptz,
            NULL::timestamptz,
            NULL::text
        )
) AS v(
    client_email_id,
    job_id,
    status,
    total_consumers,
    calls_completed,
    started_at,
    completed_at,
    results_json
) ON c.client_email_id = v.client_email_id;

INSERT INTO call_summaries (
    consumer_id,
    client_id,
    call_start_time,
    call_end_time,
    call_summary,
    job_id
)
SELECT
    co.id,
    co.client_id,
    NOW() - INTERVAL '2 hours',
    NOW() - INTERVAL '1 hour 50 minutes',
    'Caller asked about home construction services and pricing. Agent explained offerings and offered to schedule a site visit.',
    'aaaaaaaa-bbbb-cccc-dddd-000000000001'::uuid
FROM consumers AS co
JOIN clients AS c ON c.id = co.client_id
WHERE c.client_email_id = 'deepakdeshwal85@gmail.com'
  AND co.consumer_phone_number = '919900000001';

INSERT INTO call_summaries (
    consumer_id,
    client_id,
    call_start_time,
    call_end_time,
    call_summary,
    job_id
)
SELECT
    co.id,
    co.client_id,
    NOW() - INTERVAL '1 day',
    NOW() - INTERVAL '1 day' + INTERVAL '6 minutes',
    'Brief call about construction timelines. Caller requested a callback next week.',
    'aaaaaaaa-bbbb-cccc-dddd-000000000001'::uuid
FROM consumers AS co
JOIN clients AS c ON c.id = co.client_id
WHERE c.client_email_id = 'deepakdeshwal85@gmail.com'
  AND co.consumer_phone_number = '919900000002';

INSERT INTO client_voice_agent_configs (
    client_id,
    voice_agent_language,
    voice_agent_greeting_message,
    calcom_username,
    calcom_event_type_slug,
    calcom_event_type_id
)
SELECT
    c.id,
    'hi-IN',
    'Greet the caller briefly. Ask we are offerings home construction service .Say would you like anything about services. Ask what they would like to know.',
    'deepak-kumar-a7vq7q',
    '30min',
    6073963
FROM clients AS c
WHERE c.client_email_id IN (
    'deepakdeshwal85@gmail.com',
    'deepakdeshwal85@yahoo.com'
);
