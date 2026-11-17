# File storage contract v3

Files are retained on the existing `ooh-files` Kubernetes volume (20Gi,
namespace `ooh-apps`, local-path storage, PV reclaim policy Retain). The Slides
worker mounts it read-write at `/files`. From Stage 5 the Harness mounts it
read-write there too and writes only under `uploads/`; it never writes under
`outputs/`.
Stage 4 phase 2's AWS EKS copy uses the same manifests with different values:
an encrypted EBS gp3 `ooh-files` volume through `ooh-gp3`, mounted at the same
paths. The copy has separate check/test data and reclaim policy Delete; it is
destroyed after acceptance with Aziz's approval. The Droplet's retained data
and storage behaviour stay unchanged.

| Content | Key layout |
|---|---|
| Skill output | `outputs/<skill>/<correlation_id>/<file>` |
| Slides output | `outputs/slides/<correlation_id>/<safe-title>.pptx` |
| Worker health probe | `outputs/slides/.health` |
| Chat picture | `uploads/<upload id>/<safe file name>` |

The Slides worker creates `outputs/slides/` with mode 0755, writes a temporary
file in the destination folder, then renames it when complete. The title slug
contains only lower-case ASCII letters, digits and hyphens, at most 60
characters, followed by `.pptx`. A finished file is reused on a repeated job.
The worker returns `file_key`, `mime` and `summary` in `skill.result`.

The Workspace downloads through `GET /api/jobs/{job_id}/file` with its bearer
token. The Harness looks up a completed job owned by the verified user, resolves
its `file_key` under `/files/outputs/`, and refuses escapes, including symlinks.
Other users, unknown jobs, unfinished jobs and missing files receive 404.
A malformed job id receives 400. The response streams PowerPoint bytes with
`Content-Disposition: attachment` and the stored MIME type
`application/vnd.openxmlformats-officedocument.presentationml.presentation`.
The browser saves the response as a blob. There are no signed links or public
file addresses; possession of a file key never grants access.

Chat pictures (Stage 5): `POST /api/uploads` takes one PNG or JPEG as the raw
request body, at most `HA_UPLOAD_MAX_BYTES` (7 MiB), checked by its first bytes.
The Harness writes a temporary file in `uploads/<upload id>/`, then renames it.
The safe file name keeps only letters, digits, dot, underscore, space and
hyphen, at most 100 characters, with the extension `.png` or `.jpg`. The upload
id, owner, MIME type, size and SHA-256 are rows in the Harness database. A
picture is read back only through `GET /api/uploads/{upload_id}` with the
owner's bearer token; other users and unknown ids receive 404, and the resolved
path must stay under `/files/uploads/`, symlinks refused. The Harness sends a
picture to the Model Gateway inside the model call; the Gateway and the
providers never receive a file key or an address.
Nothing is deleted. This contract defines no delete route or retention cleanup.
