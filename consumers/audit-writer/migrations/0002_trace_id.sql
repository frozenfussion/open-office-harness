-- SPDX-License-Identifier: AGPL-3.0-only
ALTER TABLE trail ADD COLUMN trace_id text NULL
    CHECK (trace_id ~ '^[0-9a-f]{32}$' AND trace_id <> repeat('0', 32));
CREATE INDEX trail_trace_id ON trail(trace_id);
