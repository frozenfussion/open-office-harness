# Stage 0 — Foundation

Stage 0 accepted by Aziz on 09 Nov 2026 18:57 MYT. Implementation, merged
checks and reboot verification passed.

## Merged sources

| Source | Commit |
|---|---|
| Base tag `stage-0-base` | `d9fe9eba8c5a6581285d9c8ce2b7df28f90af142` |
| Reviewed Part A, `origin/stage-0-part-a` | `062122a` |
| Reviewed Part B, `origin/stage-0-part-b` | `ce13af4` |

Both Parts were merged without conflicts into `stage-0`. Verification ran before
this status file was added, in the clean worktree at
`~/projects/worktrees/stage-0`. The main clone was returned to `main`; its branch
was not changed by these merges. Only this status file was authored at merge.

## What was built

- Repository conventions and architecture documentation.
- Identity and storage contracts; three OpenAPI contracts; event envelope and
  payload schemas; eleven topic definitions; skill manifest and Slides schemas;
  valid examples and contract validation tests.
- Platform manifests and scripts for cert-manager, Kafka/Strimzi,
  PostgreSQL/CloudNativePG, Keycloak, namespaces, ingress and four placeholder
  pages. All three hostnames have production certificates.
- Realm `ooh`, its roles, five clients and approved audience mappers. Realm sync
  updates existing clients' mappers idempotently and stops if a client is absent.
  Login uses bootstrap environment variables inside the pod; it does not read
  the Secret on the Droplet. Temporary CLI configuration is private and removed.
- File storage on the Droplet: `ooh-files`, 20Gi, namespace `ooh-apps`. Kafka,
  PostgreSQL and files use `local-path`; apply sets each bound PV to Retain.
- Operator installation, generated secrets, ordered deployment, readiness waits,
  platform checks and first-administrator setup, with a README Quick Guide.

## Checks passed

| Check in the clean merged worktree | Result |
|---|---|
| `uv run --project contracts/check pytest` | 17 passed; Python 3.14.10 |
| `uv run --project contracts/check ruff check contracts/check` | Passed |
| `uv run --project contracts/check ruff format --check contracts/check` | Passed; two files already formatted |
| `bash -n` for every `install/*.sh` | Passed; eight scripts |
| `shellcheck install/*.sh` | Passed; eight scripts |
| `install/30-platform-apply.sh --check` | Render-only kubeconform strict validation: 39 resources in 27 files; 18 valid, zero invalid/errors, 21 custom resources explicitly skipped |

The explicitly skipped custom resource kinds are ClusterIssuer, Kafka,
KafkaNodePool, KafkaTopic, KafkaUser, Cluster, DatabaseRole, Database, Keycloak
and KeycloakRealmImport. These skips do not claim schema validation of those
resources; their live apply and readiness results are recorded below.

### Live results reported by Aziz and Claude

- Server checks, operator installation, secrets and platform application completed
  with `DONE`. The final tested Part B commit was `ce13af4`.
- Realm sync succeeded for all five clients.
- `install/40-check-platform.sh` printed **27 PASS lines and DONE**: pod readiness,
  three production certificates, four HTTPS routes, OIDC issuer, eleven topics,
  Kafka smoke read/write and refused forbidden write, PostgreSQL query, file
  volume write/read, and Retain policy for Kafka, PostgreSQL and file PVs.
- Aziz created the first administrator and signed in successfully; forced
  password change and the profile form worked. No account details are recorded.
- Reboot test passed: after `sudo reboot`, every pod came back by itself and
  `install/40-check-platform.sh` printed **27 PASS, 0 FAIL, DONE**.
- The merge checks made no cluster changes. The live results above were reported
  from the shell-tile deployment runs, not rerun by Codex during merge.

## Spec changes

The agreed build changes are recorded in `docs/specs/stage-0-foundation.md`
section 13, merged as
[pull request #3: Stage 0 spec changes agreed during the build](https://github.com/frozenfussion/open-office-harness/pull/3).
It records the Droplet/hostnames, disk storage instead of Spaces, outside access
proved by staging certificates, generic skill events, model-registry contract
changes, token audiences and the fifth client, free-form smoke messages,
stock-image Keycloak startup/recovery, download retries, live realm sync,
retained volumes, host sandbox setup and deferred identity-page cosmetics.

Later approved review clarifications are reflected in the implementation:
original `local-path` classes with PV Retain patches, the proven Keycloak database
bootstrap alongside managed database/role resources, no client creation during
realm sync, current-revision pod readiness, individual mapper operations,
semantic audience verification and pod-local bootstrap authentication.

## Open items

Open items moved to the next stages: branded sign-in page (Jira HEA-71).
