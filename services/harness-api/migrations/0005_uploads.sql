-- SPDX-License-Identifier: AGPL-3.0-only
CREATE TABLE uploads (
    id uuid PRIMARY KEY,
    user_id text NOT NULL,
    file_name text NOT NULL CHECK (length(file_name) BETWEEN 1 AND 100),
    mime text NOT NULL CHECK (mime IN ('image/png','image/jpeg')),
    size_bytes integer NOT NULL CHECK (size_bytes > 0),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    file_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deleted_at timestamptz,
    created_by text NOT NULL,
    updated_by text NOT NULL
);
CREATE INDEX uploads_user_created ON uploads(user_id,created_at);
CREATE TRIGGER uploads_no_removal BEFORE DELETE OR TRUNCATE ON uploads
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_removal();
ALTER TABLE messages ADD COLUMN upload_id uuid REFERENCES uploads(id);
CREATE UNIQUE INDEX messages_upload_once ON messages(upload_id) WHERE upload_id IS NOT NULL;
