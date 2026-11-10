# Stage 2 — Talk to AI: accepted

Stage 2 accepted by Aziz on **10 Nov 2026 20:44 MYT** ("So far, it looks good. I'd say it's accepted."). Merged into `main` and tagged `spine-v0.2`.

## What was built

- **Model Gateway** (Python, internal only): three connection types (OpenAI-compatible chat completions, OpenAI Responses, Anthropic Messages); main/backup failover before first output; per-user rate limits and daily budgets; cost from prices per million tokens; request settings and thinking-off settings as data; visible thinking events; append-only usage table; provider failures logged with status only.
- **Harness API** (Python): conversations, streamed chat, rights fail closed, reply-language system message (setting), AI-written titles, thinking pass-through and storage, access status, model requests.
- **Workspace** (Angular): sign-in and Request access, waiting/declined screens, Chat model picker, thinking switch and collapsed Thinking section, Markdown and LaTeX (sanitised), timestamps, Copy, AI titles, Request another model.
- **Control Centre** (C#): provider keys encrypted (AES-256-GCM), Gateway-only routes on internal port 8081, priorities and many models per tier, Test connection, access requests with approval rule (Everyone included), Revoke, model requests, thinking-off settings.
- **Admin Console** (Angular): Models & tiers (add, edit, Test, who may use each tier), Access requests and Model requests.
- **Keycloak**: self-registration with organisation (optional) and reason, password policy, Request access texts and mappers.

## Checks at acceptance

- `install/70-check-stage-2.sh`: 46 PASS, 0 FAIL (three providers streamed and non-streamed, keys never in logs, Gateway not public, Control Centre test-call rules, registration page, access check).
- Every Part's own checks and the contract checker (17 tests, 393 examples valid) on the merged tree.
- Aziz tested in the browser: chat on three models, Test connection, request access with a second account, approval, model request, visible thinking.

## Open items carried forward

- `install/62-check-control-centre.sh` needs Aziz's device sign-in; not rerun after the Stage 2 changes.
- Reboot test of the Droplet not done in Stage 2.
- Passing reasoning back for tool use (DeepSeek with tools) is Stage 3.
- No mail server: password resets via the Keycloak admin console (README).

## Spec

`docs/specs/stage-2-talk-to-ai.md`, sections 14 (rows 1–28), 15, 16, 16.1, 17, 17.8. Reviews and builder reports are kept in the course folder (`reviews/`).

Stage-2 head before this commit: `f7655a3`.

---

# Stage 1 — Control Centre: accepted

Stage 1 accepted by Aziz on **10 Nov 2026 01:02 MYT**. Both reviewed Parts,
the live-run fixes and the agreed spec changes are merged without conflicts
into `stage-1`, in `~/projects/worktrees/stage-1`, created from `stage-1-base`.
The acceptance commit is merged into `main` and published with tag `spine-v0.1`.

## Merged sources

| Source | Commit |
|---|---|
| Base tag `stage-1-base` | `c483be8` |
| Reviewed Part A, `origin/stage-1-part-a` | `2546f74530e58efa793121d27adc9b2d445e8614` |
| Reviewed Part B, `origin/stage-1-part-b` | `0974c4e3b3018511aff540a3a4b9bc1601dd8ba0` |
| Initial combined code | `d95c239988782b42165925c7079bbcfb3132f081` |
| Part A after live-run fix | `c96d5cc` |
| Part B after final device sign-in review | `4edfa42` |
| Combined implementation before spec merge | `d3788da` |
| `origin/main`, including merged spec pull request #5 | `b3b2649c5b6bb6f35404457ac8692d681421ec70` |
| Clean merged worktree checked for acceptance | `51e9f3b3d4771dbd96540ef7d260d004db4363aa` |

Aziz reported that Part A's re-review cleared all 11 findings with no new
findings, and Part B's final review cleared all findings with no new findings.
The checks below were rerun in the clean merged worktree before writing this
file. This status update is the only file authored during the merge step.

## What was built

- One ASP.NET Core Control Centre with deterministic rights, model and skill
  registries, approval handling and its own append-only audit trail.
- PostgreSQL migrations, separate owner/application roles, no-delete and audit
  protection triggers, transactional outbox, idempotent Kafka consumer and DLQ
  handling; signed test tokens and fake Kafka for automated tests.
- Expanded HTTP contract and examples, pinned dependencies and Docker image.
- GitHub image-build workflow, application manifests, Kafka principals,
  database/secret/deployment/check scripts, device sign-in and README Quick Guide.
- Reviewed deployment values, certificate reuse, current-revision migration
  checks, readiness at HTTP /health and liveness at TCP 8080. Check scripts keep
  credentials off command lines, handle stale check approvals, detect Kafka
  password changes, and read only this run's Kafka window with dynamic partition
  counts. The Control Centre owns its own audit; the full cross-service trail
  remains with the later Audit writer.

## Checks passed in the clean merged worktree

| Check | Result |
|---|---|
| `dotnet format --verify-no-changes` | Passed |
| `dotnet build -warnaserror` | Passed; zero warnings, zero errors |
| `dotnet test` | 105 passed, zero failed, zero skipped; database tests included |
| `uv run --project contracts/check pytest` | 17 passed; Python 3.14.10 |
| `bash -n` on every `install/*.sh` | Passed; 12 scripts |
| `shellcheck install/*.sh` | Passed; 12 scripts |
| actionlint 1.7.7 on the image workflow | Previously passed; not rerun at acceptance because the executable was unavailable |
| `kubeconform -strict` on locally rendered `deploy/` | 51 resources in 34 files; 33 valid, zero invalid/errors, 18 explicitly skipped |

PostgreSQL Database/DatabaseRole and Strimzi KafkaUser resources were validated
against schemas previously read from the installed operators. The skipped kinds
are ClusterIssuer, Kafka, KafkaNodePool, KafkaTopic, Cluster, Keycloak and
KeycloakRealmImport. These skips do not claim schema validation or live readiness
of those custom resources. Rendering used deployment values and a synthetic
image tag; it did not apply manifests or change the cluster.

## Live results reported by Aziz

- Database setup, application secrets and deployment completed with `DONE`.
  The database setup saved the test settings file with mode 600. Automated
  database tests use only `controlcentre_test`.
- Deployed image: `ghcr.io/frozenfussion/ooh-control-centre:f52d721b5eaf`.
- `install/62-check-control-centre.sh`: **49 PASS, 0 FAIL, DONE**, including
  browser device sign-in, HTTP rights/registries/approvals, Kafka messages and
  audit protections.
- After Aziz ran `sudo reboot`, `install/40-check-platform.sh` passed again
  with **27 PASS, 0 FAIL, DONE**, and `install/62-check-control-centre.sh`
  passed again with **49 PASS, 0 FAIL, DONE**.
- These live results were supplied by Aziz from his deployment and reboot runs.
  Codex's acceptance checks did not deploy, reboot or change the cluster.

## Live-run fixes and agreed spec changes

The four live-run fixes are merged:

| Commit | Fix |
|---|---|
| `c96d5cc` | Read `ASPNETCORE_` settings to listen on port 8080; disable Npgsql GSS encryption because the chiseled image has no Kerberos library |
| `e72627b` | Preserve client secret bytes without a trailing newline; report token failures safely |
| `afeefb4` | Send a PKCE S256 challenge during device sign-in |
| `53a9580` | Display the complete device verification sign-in link |

Final device sign-in review fixes and recovery instructions are included in
`4edfa42`. The agreed changes are recorded in
[Stage 1 spec section 14](specs/stage-1-control-centre.md#14-changes-agreed-during-the-build--these-override-the-sections-above),
including the live-run fixes in row 9, merged through
[pull request #5](https://github.com/frozenfussion/open-office-harness/pull/5).

## Open items for later stages

- Stage 4: switch device sign-in off again for `ooh-admin-console` when the
  Admin Console exists.
- Harness stage: rewrite `contracts/storage.md` and the storage paragraph in
  `docs/ARCHITECTURE.md` for the `ooh-files` volume.
- Stage 2: pass ordinary users' name and email; until then people may appear
  by Keycloak user id only.
- Branded sign-in page: Jira HEA-71.

---

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
