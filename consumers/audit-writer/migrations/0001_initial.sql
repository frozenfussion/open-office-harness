-- SPDX-License-Identifier: AGPL-3.0-only
CREATE TABLE trail (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    occurred_at timestamptz NOT NULL,
    user_id text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    producer text NOT NULL,
    correlation_id uuid NOT NULL,
    actor text NOT NULL, action text NOT NULL, target text NOT NULL, outcome text NOT NULL,
    model text NULL, tokens int NULL CHECK (tokens >= 0), cost_usd numeric(14,6) NULL CHECK (cost_usd >= 0), scores jsonb NULL
);
CREATE INDEX trail_correlation ON trail(correlation_id);
CREATE INDEX trail_time ON trail(occurred_at DESC, id DESC);
CREATE INDEX trail_user_time ON trail(user_id, occurred_at DESC);
CREATE FUNCTION refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'trail is append-only';
END;
$$;
CREATE TRIGGER trail_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON trail
FOR EACH STATEMENT EXECUTE FUNCTION refuse_change();
REVOKE ALL ON trail FROM PUBLIC;
DO $$
DECLARE app_role text := current_database() || '_app';
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), app_role);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', app_role);
    EXECUTE format('GRANT SELECT, INSERT ON trail TO %I', app_role);
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE trail_id_seq TO %I', app_role);
END;
$$;
