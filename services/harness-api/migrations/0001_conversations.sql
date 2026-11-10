-- SPDX-License-Identifier: AGPL-3.0-only
CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    user_id text NOT NULL,
    title text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz,
    created_by text NOT NULL,
    updated_by text NOT NULL
);
CREATE INDEX conversations_user_updated ON conversations(user_id, updated_at DESC, id DESC)
    WHERE deleted_at IS NULL;
CREATE TABLE messages (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id),
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    tier integer CHECK (tier > 0),
    model_entry_id uuid,
    model_title text,
    input_tokens integer CHECK (input_tokens >= 0),
    output_tokens integer CHECK (output_tokens >= 0),
    note text,
    outcome text NOT NULL CHECK (outcome IN ('completed', 'failed', 'tool_requested')),
    created_at timestamptz NOT NULL,
    created_by text NOT NULL
);
CREATE INDEX messages_conversation_time ON messages(conversation_id, created_at, id);
CREATE FUNCTION refuse_removal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Rows cannot be removed';
END;
$$;
CREATE FUNCTION refuse_message_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Messages are append-only';
END;
$$;
CREATE TRIGGER conversations_no_removal BEFORE DELETE OR TRUNCATE ON conversations
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
CREATE TRIGGER messages_no_removal BEFORE DELETE OR TRUNCATE ON messages
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
CREATE TRIGGER messages_no_update BEFORE UPDATE ON messages
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_message_change();
