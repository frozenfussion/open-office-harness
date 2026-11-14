# File storage contract v2

Files are retained on the existing `ooh-files` Kubernetes volume (20Gi,
namespace `ooh-apps`, local-path storage, PV reclaim policy Retain). The Slides
worker mounts it read-write at `/files`; the Harness mounts it read-only there.
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

Uploads remain unbuilt: `POST /api/uploads` returns 503 `not_built_yet`.
Nothing is deleted. This contract defines no delete route or retention cleanup.
