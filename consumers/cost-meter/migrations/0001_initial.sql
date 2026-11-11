-- SPDX-License-Identifier: AGPL-3.0-only
CREATE TABLE model_costs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    occurred_at timestamptz NOT NULL,
    user_id text NOT NULL,
    action text NOT NULL CHECK (action IN ('model.call', 'model.classify')),
    model text NOT NULL, model_entry_id text NOT NULL, tokens int NOT NULL CHECK (tokens >= 0), cost_usd numeric(14,6) NOT NULL CHECK (cost_usd >= 0)
);
CREATE INDEX model_costs_time ON model_costs(occurred_at);
CREATE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'model_costs is append-only';
END;
$$;
CREATE TRIGGER model_costs_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON model_costs
FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
REVOKE ALL ON model_costs FROM PUBLIC;
DO $$
DECLARE app_role text := current_database() || '_app';
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), app_role);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', app_role);
    EXECUTE format('GRANT SELECT, INSERT ON model_costs TO %I', app_role);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE model_costs_id_seq TO %I', app_role);
END;
$$;
