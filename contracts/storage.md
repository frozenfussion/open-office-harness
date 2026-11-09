# Object storage contract v1

The S3-compatible bucket is private: DigitalOcean Spaces now, Amazon S3 in
Stage 6. Buckets are never public. Credentials exist only in Kubernetes Secrets.

| Content | Key layout |
|---|---|
| Uploaded file | uploads/<user_id>/<uuid>-<name> |
| Skill output | outputs/<skill>/<correlation_id>/<file> |
| Platform storage probe | checks/<unique-name> |

The Harness validates names and object ownership; names cannot introduce path
segments or traversal. Workers write their skill's outputs and return file_key,
mime and summary, not public links. An object key is an identifier, not authority.

Downloads go through GET /api/files/{key}. The Harness checks the authenticated
user's access before issuing a short-lived signed URL with expires_at in UTC.
The key must be percent encoded as a single path parameter. Signed URLs are
sensitive temporary capabilities: do not persist or log them. Link lifetime is
set when the Harness is implemented. No public bucket URLs or secret values
are stored in contracts. Objects are retained; these contracts define no delete.
