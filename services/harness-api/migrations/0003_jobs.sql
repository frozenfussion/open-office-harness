-- SPDX-License-Identifier: AGPL-3.0-only
CREATE TABLE jobs (
    id uuid PRIMARY KEY,
    user_id text NOT NULL,
    conversation_id uuid REFERENCES conversations(id),
    message_id uuid REFERENCES messages(id),
    skill text NOT NULL,
    skill_version text NOT NULL,
    input jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('awaiting_approval','queued','completed','failed','rejected')),
    output jsonb,
    error jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    created_by text NOT NULL,
    updated_by text NOT NULL
);
CREATE INDEX jobs_user_created ON jobs(user_id,created_at DESC,id DESC);
CREATE TRIGGER jobs_no_removal BEFORE DELETE OR TRUNCATE ON jobs
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
CREATE TABLE processed_events (
    event_id uuid PRIMARY KEY,
    topic text NOT NULL,
    handled_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER processed_events_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON processed_events
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_message_change();

ALTER TABLE messages ADD COLUMN reasoning_state jsonb;
