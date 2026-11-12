# Stage 4 phase 1 - accepted (12 Nov 2026)

Aziz accepted Stage 4 phase 1 on **12 Nov 2026, 22:56 MYT**, at `stage-4` commit
`7c721a4de601` (all nine images built and deployed with that tag). Tag `class-start`.
Merge into `main` waits for Aziz's yes.

## What was built

- OpenTelemetry tracing from every service into Jaeger inside the cluster; attribute allow-list; Kafka `traceparent` headers; public requests always start a new trace; `trace_id` on every audit row.
- Admin Console: Trace view on the Audit screen (opens under the clicked row, with Close); Failed messages screen with Replay (`POST /api/admin/dead-letters/{id}/replay`, `dead_letter_replays` table, audit row for every replay).
- Class demos `install/79-demo.sh` (duplicate, worker-down, dead-letter) and check `install/78-check-stage-4.sh`.
- Workspace: a saved chat link (`/?conversation=<id>`) opens that chat after sign-in; words in chat tables never break mid-word.

## What was checked

| Check | Result |
|---|---|
| `40`, `62`, `70`, `77`, `78` at `ec1973f72c4f` | PASS before and after `sudo reboot` (198 PASS, 0 FAIL) |
| Three demos in the browser | duplicate, worker-down, dead-letter with Replay: all worked |
| Browser | Audit trace for a chat and a Slides job; saved link through sign-in; invalid saved link ignored; whole words in tables, also at phone width |
| Independent audit (`reviews/stage-4-audit.md`) | found an outside trace id adopted by the Control Centre, plus smaller issues; fixed in one fix round (`3ef4adb`, `7c721a4`), review and re-review with no findings |
| `40`, `62`, `70`, `77`, `78` at `7c721a4de601` | 199 PASS, 0 FAIL; forged `traceparent` through the admin address refused and absent from Jaeger |
| Clean worktree | contract tests 18 passed (`ec1973f`, contracts unchanged since); `bash -n`, `shellcheck` clean; `kubeconform -strict` 0 invalid |

## Recorded deviation

- The Control Centre sends traces with its own small OTLP HTTP/protobuf sender (`PrivateSpanExporter.cs`) instead of the `OpenTelemetry.Exporter.OpenTelemetryProtocol` package; it reads `OTEL_EXPORTER_OTLP_PROTOCOL` and warns once if it is not `http/protobuf`.

## Open for later

- Gateway "send audit.events" spans end after their parent (cosmetic, timeline bars run past it).
- Any pod in the cluster can read Jaeger's query API (the spec does not forbid it).
- Jaeger keeps traces in memory; a restart empties it (fine for class, not for production).
- The audit row for chat-title calls shows the person as `title-<user id>`.
- Phase 2 (AWS via Terraform, tag `eks-ready`): spec `stage-4b-aws.md` still to write.

---

# Stage 3 - accepted (12 Nov 2026)

Aziz accepted Stage 3 on **12 Nov 2026, 15:36 MYT**, at `stage-3` commit
`554a187f84c0` (all nine images built and deployed with that tag). Merged into
`main`; tag `spine-v0.3`.

## What was checked

| Check | Result |
|---|---|
| Clean-worktree checks (all services, contracts, scripts, manifests) | PASS (independent audit, 12 Nov) |
| `40`, `62`, `70`, `77 554a187f84c0` after `sudo reboot` | all PASS, 0 FAIL (12 Nov 15:13-15:31) |
| Aziz in the browser | branded sign-in; Admin Console sign-in with username and with email; Slides deck made and downloaded (11 and 12 Nov, also after the reboot); Auto routing simple question -> tier 1, hard question -> tier 2; Slides right removed -> no Slides tool offered |

## Changes after phase 2 (12 Nov)

- Admin Console sign-in loop fixed: the screen navigation no longer rewrites the address before sign-in finishes (`c379610`, `51c40fc`).
- Models screen refreshes health after Test, Save and Switch off (`69248ec`).
- Routing: the tier 2 rule is written down and is the routing question; threshold 0.5 from a 20-question labelled set (`docs/routing/`); Jev main classifier, DeepSeek backup, temperature 0 (spec section 14 row 15; D096, D097).

## Open for later (not in the Stage 3 spec)

- Workspace: a saved chat link opened while signed out lands on a new chat after sign-in (the conversation id is not carried through sign-in).
- Workspace: tables in chat answers break short words (the design system's `overflow-wrap: anywhere` on message bodies also applies inside tables).

---

# History: Stage 3 phase 1 merge (11 Nov 2026)

The reviewed phase 1 Parts were merged locally on **11 Nov 2026**, in
`~/projects/worktrees/stage-3`, on branch `stage-3`. All five sources merged in
the requested order without conflicts. The branch has **not been pushed**;
Aziz's approval is required before that step. Nothing was deployed and Stage 3
has not been accepted.

## Merged sources

| Source | Commit |
|---|---|
| Base tag `stage-3-base` | `00207e7932e4` |
| Spec decisions, section 14 rows 5–11, `origin/stage-3-spec-rows` | `163fb1ab5342` |
| Reviewed Part A, `origin/stage-3-part-a` | `12d413e882f4` |
| Reviewed Part B, `origin/stage-3-part-b` | `f31937e213a0` |
| Reviewed Part C, `origin/stage-3-part-c` | `f2f110184d60` |
| Reviewed Part D, `origin/stage-3-part-d` | `d310e9d008a9` |
| Combined source commit checked before this status-only update | `373b0b930064` |

## What was built

- **Part A — Harness API and Slides worker:** tool rounds with pinned follow-up
  calls and private reasoning history; durable jobs and approval decisions,
  Kafka events, user-scoped SSE, owned file downloads and skill requests. The
  worker builds PowerPoint files on the retained volume, reuses finished files,
  retries and sends dead letters. Consumer recovery, bounded background chat
  publishing and individual delivery callbacks keep Kafka failures from taking
  chat down. Packages, tests, images, manifests, setup/deploy scripts and storage
  contract are included.
- **Part B — Model Gateway and consumers:** tool/reasoning support, classification
  connections, model health reports and background audit publication. The audit
  writer, cost meter and safety watcher validate events, handle duplicates and
  retries, and expose the specified internal views or safety approvals. Their
  packages, protected databases, tests, images, manifests and scripts are included.
- **Part C — Workspace and platform:** Jobs panel/cards, authenticated downloads,
  requestable skills and SSE reconnect/reload; branded sign-in; new Kafka topics
  and principals, service clients and audiences; temporary check-client helper
  and stage check. Root Quick Guide and architecture/identity documents describe
  the merged phase 1 flow.
- **Part D — Control Centre and Admin Console:** skill requests and grants,
  approval handling, model/service health, dead letters, overview figures and
  audit proxy, plus the Overview, Approvals, People & rights and Audit screens.
  Service-account filtering, contracts, migrations, tests and deployment settings
  are included.

## Checks on the clean merged worktree

Every Python package ran `uv sync --frozen`, `ruff check`,
`ruff format --check` and `pytest`. The private test settings were loaded for
Harness, Gateway, audit writer and cost meter; Control Centre tests read their
existing private test settings. No settings or credentials were printed.
Database tests used only the isolated test databases. Protection assertions
that attempt forbidden changes run in rolled-back transactions. All final test suites have zero failures
and zero skips: **1,121 tests passed** (753 Python/contract, 123 Angular and
245 Control Centre).

| Check | Result |
|---|---|
| Harness API | 312 tests passed; frozen sync and both Ruff checks passed |
| Model Gateway | 321 tests passed; frozen sync and both Ruff checks passed |
| Slides worker | 18 tests passed; frozen sync and both Ruff checks passed |
| Audit writer | 24 tests passed; database included; frozen sync and both Ruff checks passed |
| Cost meter | 29 tests passed; database included; frozen sync and both Ruff checks passed |
| Safety watcher | 31 tests passed; frozen sync and both Ruff checks passed |
| Contract checker | 18 tests passed; frozen sync and both Ruff checks passed; 487 indexed examples |
| Workspace | `npm ci`, `npx ng build`, `npx ng test --watch=false` passed; 95 tests in 6 files |
| Admin Console | `npm ci`, `npx ng build`, `npx ng test --watch=false` passed; 28 tests in 2 files |
| Control Centre formatting | `dotnet format --verify-no-changes --no-restore` passed |
| Control Centre build | `dotnet build -warnaserror` with build servers disabled passed; 0 warnings, 0 errors |
| Control Centre tests | 245 passed, 0 failed, 0 skipped; database tests included |
| EF migration/model check | `dotnet ef migrations has-pending-model-changes` passed; no pending model changes |
| Shell syntax | `bash -n` passed for all 27 `install/*.sh` and `install/lib/*.sh` files |
| ShellCheck | `shellcheck -x install/*.sh install/lib/*.sh` passed with the merged helper present |
| Kubernetes manifests | `kubeconform -strict`: 108 valid resources in 71 files; 0 invalid, 0 errors, 0 skipped |
| Git | Clean merged source worktree before this status update; whitespace check passed |

Manifest validation used locally rendered deployment values, the checked merge
commit's image tag and the same configuration/theme checksum substitutions as
the deploy scripts. The certificate contact was a synthetic validation address;
the admin issuer was read from the existing Ingress. The theme ConfigMap was
rendered with the platform script's client-only dry run. Installed CRD schemas
were obtained through read-only `kubectl get`; conversion supplied the standard
resource envelope fields omitted by the Keycloak schemas and applied strict
object-property checks. No custom resource kind was skipped. This was schema
validation only, not an apply, readiness check or real provider test.

Non-failing notices: the pinned Python test-client stack emits an
httpx/Starlette deprecation warning in five packages. Both `npm ci` runs report
zero vulnerabilities and notices about four dependency install scripts not
covered by npm's allowScripts setting; the builds and tests still pass. No
package versions or approval settings were changed. .NET checks used disabled
build servers and end with build-server shutdown.

## Open items before deployment and phase 2

- Await Aziz's approval before pushing `stage-3`. No merge image workflow has
  been started; build all required images for the final pushed commit before
  deployment, and confirm the four new packages are public as the Quick Guide
  describes.
- Claude deploys in the root README order while Aziz watches. The Slides grant
  and classification model must be configured through the Admin Console at the
  specified points. The live platform, Control Centre, Stage 2 and Stage 3
  checks have not been run for this merge.
- Aziz's browser checks, download/open/ownership checks and reboot checks remain
  outstanding. These local results do not claim any live acceptance result.
- Create and push `pre-routing` only after phase 1 has been deployed and checked.
  Part E's classifier routing starts from that tag; it is not part of this merge.

The status update is the only newly authored repository file in this merge
step. Product code and the reviewed Parts were not changed. No sudo, Kubernetes
resource change, background service/server/watcher launch, live AI call, push or stage
acceptance/tag was performed during the merge checks.

---

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
