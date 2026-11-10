-- SPDX-License-Identifier: AGPL-3.0-only
CREATE TABLE usage (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    model_entry_id uuid NOT NULL,
    user_id text NOT NULL,
    purpose text NOT NULL,
    tier int NULL CHECK (tier > 0),
    outcome text NOT NULL CHECK (outcome IN ('ok', 'failed', 'skipped_rate', 'skipped_budget')),
    input_tokens int NOT NULL CHECK (input_tokens >= 0),
    output_tokens int NOT NULL CHECK (output_tokens >= 0),
    cost_usd numeric(14,6) NOT NULL CHECK (cost_usd >= 0),
    duration_ms int NOT NULL CHECK (duration_ms >= 0)
);
CREATE INDEX usage_user_window ON usage(model_entry_id, user_id, occurred_at);
CREATE INDEX usage_budget_window ON usage(model_entry_id, occurred_at);
CREATE FUNCTION refuse_usage_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'usage is append-only';
END;
$$;
CREATE TRIGGER usage_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON usage
FOR EACH STATEMENT EXECUTE FUNCTION refuse_usage_change();
DO $$
DECLARE app_role text := current_database() || '_app';
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), app_role);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', app_role);
    EXECUTE format('GRANT SELECT, INSERT ON usage TO %I', app_role);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE usage_id_seq TO %I', app_role);
END;
$$;
