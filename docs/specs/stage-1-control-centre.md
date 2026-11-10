# Stage 1 — Control Centre (rights, registries, approvals, its own audit)

Written 2026-11-09 by Claude (orchestrator). Read `00-GLOBAL-RULES.md` first; it applies in full.
**Base commit:** `main` right after this spec is merged. Before any Part starts, Codex tags that commit `stage-1-base` and pushes the tag (`git tag -a stage-1-base -m "Stage 1 base" && git push origin stage-1-base`). Every Part starts from that tag.
**Tag when accepted:** `spine-v0.1`.

## 0. Aziz's words and decisions (Malaysia time)

- 07 Nov 16:26: Rights are fixed rules in the Control Centre, never decided by an AI; the classifier only suggests.
- 08 Nov 12:00: A tier is a field on each chat model entry; creating a tier creates its right.
- 08 Nov: Sign-ups go through Approvals like every other human decision (later stage).
- 09 Nov 16:18: "Do not unnecessarily add a tech stack." Always the simplest step that does not cut corners. Files live in the Kubernetes volume `ooh-files` on the Droplet disk: no Spaces, no S3 server (Stage 0 section 13, change 2).
- 09 Nov 20:07: GitHub builds the Docker images: "Yes, I agree."
- 09 Nov 20:19: Stage 1 is split by code vs. getting it running: "Yes, I do." Builders: Codex (GPT-6.1-Sol, medium, fast). Checks and reviews: Claude Code.
- 09 Nov 20:59: after the spec review, "yes proceed": two database roles (owner for migrations, a separate role for the running program); the builders' test-database settings file is an accepted exception (section 14); the file-storage contract rewrite moves to the stage that builds the Harness.

## 1. Purpose

Replace the placeholder at `https://admin.faysalaziz.com/api` with the real **Control Centre**: one C# program (modular monolith) that
- answers **rights checks** with fixed rules (fail closed);
- keeps the **model registry** (which model serves which purpose and tier) and the **skill registry** (skill manifests);
- receives **approval requests** from Kafka, lets an admin decide them, and publishes the decision to Kafka;
- records **its own audit trail** (every change it makes), append-only and enforced by the database, and publishes each record to `audit.events`.

No AI model is called. No user interface (the Admin Console is Stage 4). No DLQ view or replay (deferred, as `contracts/identity.md` says).

## 2. Done when (all of these)

1. GitHub Actions builds the image `ghcr.io/frozenfussion/ooh-control-centre:<first 12 characters of the commit hash>` on every push that changes `services/control-centre/` (and on demand), the run is green, and the image can be pulled **without logging in** (public).
2. On harness, from the `stage-1` worktree (`cd ~/projects/worktrees/stage-1`), Aziz runs `install/59-control-centre-databases.sh`, `install/60-control-centre-secrets.sh` and `install/61-control-centre-deploy.sh`; each ends with `DONE`. The pod in `ooh-apps` is Ready; the database migrations ran in the init container; the `control-centre-api` placeholder Deployment and Service are gone.
3. `install/62-check-control-centre.sh` prints `PASS` for every line and ends with `DONE`. Aziz signs in once in his browser during the run (device sign-in, section 7). It checks:
   a. `GET https://admin.faysalaziz.com/api/rights/me?user_id=x` without a token → 401;
   b. a valid token without audience `ooh-control-centre` (the `ooh-control-centre` client's own service-account token: it has no audience mappers) → 401;
   c. as the Harness service account: `POST /api/rights/check` for a new test user id (`stage-check-<random>`) with no grants → `allowed:false`, `decided_by:"no-grant"`;
   d. as the Model Gateway service account: `GET /api/models?purpose=classification` → 200 (a list); as the Harness service account the same call → 403;
   e. as Aziz (admin): first remove any active entry with model_id `stage-check` left by an earlier run; create a chat model entry with purpose `chat`, tier 2, role `backup`, location `cloud`, api_type `stage-check`, endpoint_url `https://stage-check.invalid`, model_id `stage-check`, secret_ref `stage-check-none`, rate limit 1, budget 0 → the right `chat.tier.2` exists; grant it to the test user; the Harness service account's rights check for that user and tier → `allowed:true`; remove the grant → `allowed:false`; remove the check's model entry at the end. The right `chat.tier.2` stays (rights are never removed); this is accepted;
   f. as Aziz: register the Slides skill from `contracts/skills/slides/manifest.json` (re-running is harmless); as the Harness service account, `GET /api/skills?user_id=<test user>` lists it only after `skill.slides` is granted to the test user;
   g. a check principal publishes an `approval.requested` event (action `stage.check`, a new correlation_id) to `approvals.requested` **twice with the same event_id**; the script asks `GET /api/admin/approvals?correlation_id=<id>` until one appears (at most 60 s), waits 10 s more, and the count is still exactly one pending approval;
   h. as Aziz: approve it → an `approval.decided` event with the same `correlation_id` is read back from `approvals.decided`;
   i. the Control Centre's audit query shows this run's grant, model entry and decision, and a `slides` skill row from any run (filter `target=slides`); `audit.event` messages are read back from `audit.events` for this run's own rows (and for the Slides row only when this run created it), reading only from the newest offsets taken just before the check's writes;
   j. in the PostgreSQL pod, `psql -d controlcentre`, each statement inside `BEGIN; … ROLLBACK;` on `audit_log WHERE id = (SELECT min(id) FROM audit_log)`: as `SET ROLE controlcentre_app`, `UPDATE` and `DELETE` fail with "permission denied"; as `SET ROLE controlcentre` (the owner), `UPDATE` and `DELETE` fail with the trigger's error. A statement that succeeds is a FAIL; the rollback means nothing is lost either way.
4. After `sudo reboot`, `install/40-check-platform.sh` and `install/62-check-control-centre.sh` pass again without anyone touching the server (allow 5 minutes).
5. In a clean worktree of `stage-1`: `dotnet format --verify-no-changes`, `dotnet build -warnaserror` and `dotnet test` pass in `services/control-centre`; `uv run --project contracts/check pytest` passes; `bash -n` and `shellcheck` are clean for every `install/*.sh`; `kubeconform -strict` passes on `deploy/`.
6. `README.md` Quick Guide covers everything in section 9; `docs/STATUS.md` says Stage 1 is done and lists what was checked.

## 3. Prerequisites (before the builders start)

1. **.NET SDK on harness, in Aziz's home folder (no sudo).** Type this in your harness terminal, Shell tile (Claude may type it there; Aziz presses Enter). The folder doesn't matter. It asks for no password. It installs the .NET 10 SDK into `~/.dotnet`, links `dotnet` into `~/.local/bin` (already on the PATH that `~/.profile` gives every shell, including Codex's), and stops on any failure:
   ```
   if curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh && bash /tmp/dotnet-install.sh --version 10.0.403 --install-dir "$HOME/.dotnet"; then mkdir -p "$HOME/.local/bin" && ln -sf "$HOME/.dotnet/dotnet" "$HOME/.local/bin/dotnet" && { grep -q DOTNET_ROOT "$HOME/.profile" || printf '\nexport DOTNET_ROOT="$HOME/.dotnet"\nexport DOTNET_CLI_TELEMETRY_OPTOUT=1\n' >> "$HOME/.profile"; } && . "$HOME/.profile" && dotnet --version; else echo "STOP: .NET install failed"; fi
   ```
   Good result: `10.0.403`.
2. **Databases** (Part B writes the script first, Aziz runs it before Part A runs database tests): `install/59-control-centre-databases.sh` (section 7, Part B). Until then Part A runs only the tests that need no database and says so in its report.

## 4. Decisions for this stage (fixed; versions verified 09 Nov 2026 from dotnet release metadata, nuget.org, mcr.microsoft.com and GitHub releases)

| Item | Decision | Why |
|---|---|---|
| Runtime | .NET **10.0.14**, SDK **10.0.403**, ASP.NET Core minimal APIs | .NET 10 is the long-term release (to Nov 2028); .NET 11 is only a release candidate |
| Data | EF Core **10.0.14** + Npgsql.EntityFrameworkCore.PostgreSQL **10.0.3**; EF Core migrations only | Global rules |
| Tokens | Microsoft.AspNetCore.Authentication.JwtBearer **10.0.14** | Microsoft's own OIDC/JWT validation |
| Kafka | Confluent.Kafka **2.16.0**, SCRAM-SHA-512 on the internal listener 9092 | The standard .NET Kafka client |
| Tests | xunit.v3 **4.0.3**, xunit.runner.visualstudio **4.0.1**, Microsoft.NET.Test.Sdk **18.11.0**, Microsoft.AspNetCore.Mvc.Testing **10.0.14** | Global rules say xUnit; the runner lets `dotnet test` find the tests; Mvc.Testing runs the real routes in memory |
| Migrations tooling | Microsoft.EntityFrameworkCore.Design **10.0.14**; `dotnet-ef` **10.0.14** as a local tool (`.config/dotnet-tools.json` in `services/control-centre`) | Needed to create EF Core migrations; local tool = pinned, nothing installed system-wide |
| JSON Schema checks | JsonSchema.Net **9.6.0** | .NET has no built-in JSON Schema validator; needed for skill manifests and the event envelope |
| Images | build: `mcr.microsoft.com/dotnet/sdk:10.0.403-noble`; run: `mcr.microsoft.com/dotnet/aspnet:10.0.14-noble-chiseled` | Official Microsoft images on Ubuntu 24.04; chiseled = small, no shell, non-root |
| Image build | GitHub Actions, `.github/workflows/control-centre-image.yml`; actions pinned by full commit SHA: actions/checkout v7.0.1, docker/setup-buildx-action v4.4.1, docker/login-action v4.8.0, docker/build-push-action v7.4.0; login with the workflow's own `GITHUB_TOKEN` (`packages: write`, `contents: read`) | Free for a public repo; nothing added to the Droplet; the image is public after the one-time switch if needed (section 12 item 4) |
| Database | `controlcentre` and `controlcentre_test` on `ooh-pg`, made by CloudNativePG `Database` + `DatabaseRole` resources, reclaim policy retain. **Two roles per database:** the owner (`controlcentre`, `controlcentre_test`) is used only to apply migrations; the running program (and the tests) use `controlcentre_app` / `controlcentre_test_app`, which own nothing and get `SELECT, INSERT` on `audit_log`, `SELECT, INSERT, UPDATE` on the other tables, no `DELETE`, no `TRUNCATE`. Grants are set by the migrations | An owner could switch off the audit trigger; the program's role cannot. Same as HOORA AI. Tests never touch the live database |
| Migrations | the same image run with the argument `migrate` as an init container, connected as the owner role (`CC_DB_MIGRATE_CONNECTION`): it applies pending migrations and exits; the main container never migrates and never sees the owner's password | One writer of the schema, safe when there is more than one copy (EKS later) |
| Kafka user | `KafkaUser control-centre` with exactly the rights in `contracts/identity.md`; consumer group `control-centre` | Contract |
| Getting events out safely | an **outbox table** in `controlcentre`: a change, its audit row and its outgoing message are saved in one transaction; a background loop in the same program publishes unsent outbox rows and marks them sent. DLQ messages also go through the outbox | Without it a crash between "saved" and "published" loses a decision. No new technology: one table and one loop |
| Consumer rules | `approvals.requested`: ignore an `event_id` already handled (table `processed_events`); 3 tries with 1 s, 5 s, 15 s waits; then a `dlq.entry` to `dlq.approvals.requested` (through the outbox) and move on | Global rules |
| Outgoing message fields | every envelope: `producer` `control-centre`, a new `event_id`. Change made over HTTP by an admin: `user_id` = the admin's `sub`, `correlation_id` = one new UUID per request. Change the program makes on its own from a Kafka message (an approval created from `approval.requested`, a message sent to the DLQ): `user_id` and `correlation_id` = those of the incoming message, audit `actor` = `system`; for a message that cannot be read at all: `user_id` = `system`, a new UUID as `correlation_id` and key. `approval.decided`: `user_id` = the requester's, `correlation_id` = the request's. `audit.event` carries only `actor, action, target, outcome`; `detail` stays in `audit_log`. A `dlq.entry` for a message that cannot be read: Kafka key = a new UUID | The envelope and payload schemas require these; nothing left to guess |
| Hostname | `admin.faysalaziz.com/api/*` → the Control Centre (the Ingress keeps the `/api` prefix); `/health` is only for Kubernetes probes, not public | Three-name design |
| People | the Control Centre knows a person by `user_id` (= Keycloak `sub`). Table `people` (user_id, email, name, first_seen_at, last_seen_at) is filled when a person's own token reaches the Control Centre (in Stage 1: admins through the device sign-in) or when an admin grants them something (then only the id is known). **Known limit:** ordinary users appear by id only until a later stage passes their name and email (decided in Stage 2) | No call to Keycloak's admin API needed |
| Admin sign-in for scripts | Keycloak's **device sign-in** (OAuth 2.0 Device Authorization Grant) switched on for the existing public client `ooh-admin-console`; the check script shows a link and code, Aziz signs in in his browser (like `gh auth login`). The access and refresh tokens stay in shell variables, never printed or saved; the script refreshes the access token before each admin call (tokens last 5 minutes). **Accepted only until the Admin Console exists:** Stage 4 switches device sign-in off again through `35-realm-sync.sh` (it lets anyone send real-looking sign-in codes) | Lets Aziz act as admin before the Admin Console exists, with his own identity. Nothing new installed |
| Tokens and secrets on the command line | every token and client secret reaches `curl` on standard input (`curl --config -` or `-H @-`), never as an argument (other processes could read it with `ps`). Service-account secrets: `kcadm.sh get clients/<id>/client-secret` inside the Keycloak pod (logged in as in `35-realm-sync.sh`), captured on harness into a variable, then sent to the token endpoint on standard input. Same accepted exposure as Stage 0 section 13 change 16. Applies to 59, 60, 61 and 62 | Secrets never visible to other processes or printed |
| Check principal | `KafkaUser ooh-stage-check`: write `approvals.requested`; read `approvals.decided` and `audit.events`; group `ooh-stage-check` only. Listed in `contracts/identity.md` as a check principal; `contracts/events/topics.yaml` lists only production principals and does not change | The check needs to play the requester; it must not borrow a real service's identity |

## 5. Data model (Control Centre database `controlcentre`)

**Business tables** (`people`, `rights`, `grants`, `model_entries`, `skills`, `approvals`): UUID primary key, `created_at`, `updated_at`, `deleted_at`, `created_by`, `updated_by` (user_id or `system`). "Remove" sets `deleted_at`; "restore" clears it. **System tables** (`processed_events`, `outbox`): their own columns, no `deleted_at`; the only update allowed is setting `outbox.sent_at`. Times in UTC (`timestamptz`). No hard delete anywhere: a statement trigger refuses `DELETE` and `TRUNCATE` on every table, with **no exception for any role**. Database tests isolate themselves by running each test in a transaction that is rolled back, or by using unique ids, and never assume a table is empty.

| Table | Holds |
|---|---|
| `people` | user_id (unique), email, name, first_seen_at, last_seen_at |
| `rights` | key (unique, e.g. `chat.tier.2`, `skill.slides`, `image.generate`), description, source (`tier` / `skill` / `builtin`) |
| `grants` | right_key, subject_type (`user` / `everyone`), subject_id (user_id, or null for everyone). Unique among active rows |
| `model_entries` | the fields of the registry answer in `contracts/http/control-centre.openapi.yaml` (purpose, tier for chat only, role main/backup, location, api_type, endpoint_url, model_id, secret_ref = the **name** of a Kubernetes Secret whose key `api-key` the Gateway reads; never a credential, rate_limit_per_minute, daily_budget, health). At most one active `main` and one active `backup` per purpose + tier. `health` starts as `unknown` (the Gateway reports it from Stage 2) |
| `skills` | name (unique), version, manifest (jsonb, validated against `contracts/skills/manifest.schema.json`) |
| `approvals` | request event_id, correlation_id, requester user_id, producer, action, details, risk, requested_by, status (`pending` / `approved` / `rejected`), decided_by, note, decided_at |
| `processed_events` | event_id (primary key), topic, processed_at |
| `outbox` | topic, key (= correlation_id), envelope (jsonb), created_at, sent_at |
| `audit_log` | id (bigint identity), occurred_at, actor, action, target, outcome, detail (jsonb: before/after; secret values never stored), correlation_id. **Append-only:** a trigger refuses `UPDATE`, `DELETE` and `TRUNCATE`; the program's role has only `SELECT, INSERT` and cannot remove the trigger |

Built-in rights created by the first migration: `image.generate`. Creating a chat model entry with a new tier creates `chat.tier.<n>`; registering a skill creates the right named in its manifest. Rights are never removed automatically.

## 6. HTTP routes (all JSON; every route except `/health` needs a valid token with audience `ooh-control-centre`)

Who may call is decided by the token: **admin** = realm role `ooh-admin`; **Harness** = `azp` `ooh-harness-api`; **Gateway** = `azp` `ooh-model-gateway`; **self** = a user token whose `sub` equals the `user_id` in the request.

| Route | Who | Does |
|---|---|---|
| `GET /health` | anyone (probes) | `{"status":"ok"}` when the database answers, else 503 |
| `POST /api/rights/check` | Harness, admin, self | existing contract. `chat.tier` + target `"n"` → right `chat.tier.n`; `skill.use` + target skill name → the active skill's right; `image.generate` → `image.generate` (its `target` is required by the contract and ignored). A `chat.tier` target that is not a positive integer → 400. Allowed if an active grant exists for the user or for everyone. `decided_by`: `grant:user`, `grant:everyone` or `no-grant`. Unknown tier or skill → `allowed:false`. Any internal error → 503 (callers treat it as not allowed) |
| `GET /api/rights/me` | Harness, admin, self | existing contract |
| `GET /api/skills` | Harness, admin, self | existing contract: only active skills whose right the user holds |
| `GET /api/models` | Gateway only | existing contract |
| `GET /api/admin/people`, `GET /api/admin/people/{user_id}` | admin | people with their active grants |
| `GET /api/admin/rights` | admin | all rights |
| `POST /api/admin/grants`, `DELETE /api/admin/grants/{id}` | admin | grant a right to a user or to everyone; remove (sets `deleted_at`) |
| `GET/POST /api/admin/models`, `GET/PUT/DELETE /api/admin/models/{id}` | admin | the model registry (DELETE = remove) |
| `GET/POST /api/admin/skills`, `GET/PUT/DELETE /api/admin/skills/{name}` | admin | the skill registry (POST of an existing name with the same version changes nothing and returns 200) |
| `GET /api/admin/approvals?status=&correlation_id=&limit=&before=`, `GET /api/admin/approvals/{id}` | admin | approvals, newest first; ordered by `(created_at, id)`; `before` = `<created_at>,<id>` of the last row seen (UTC, ISO 8601), so rows with the same time are neither skipped nor repeated |
| `POST /api/admin/approvals/{id}/decision` | admin | `{approved, note}`; only a pending approval (otherwise 409); saves the decision, its audit row and the outgoing `approval.decided` in one transaction |
| `GET /api/admin/audit?actor=&action=&target=&correlation_id=&before_id=&limit=` | admin | the Control Centre's own audit rows, newest first (limit 1–200, default 50). The full cross-service trail belongs to the Audit writer (Stage 3) |

Inputs are validated (unknown fields refused); lists use `limit` 1–200 (default 50); errors use the contract's `Error` shape. Every write appends an audit row and an outbox `audit.event` in the same transaction. Logs never contain request bodies or tokens. Part A corrects the OpenAPI description of `secret_ref` to: "names a Kubernetes Secret (the Gateway reads its key api-key); never contains credentials". A user's own token reaching the Control Centre updates `people` (email and name from the token).

## 7. Parallel Parts

Two Codex windows at the same time, each in its own worktree from `stage-1-base`. **Rule: Part A changes no file Part B lists, and the reverse.** Nobody changes the files in section 10.

### Part A — Control Centre code (branch `stage-1-part-a`, Codex A, tile 0)

Files (only these):
```
services/control-centre/**                   (solution, projects, migrations, tests, Dockerfile, .dockerignore, README.md)
contracts/http/control-centre.openapi.yaml   (add every route in section 6; keep the existing four unchanged, except the `secret_ref` description, section 6)
contracts/examples/http/control-centre.*     (one example per new route and status)
contracts/examples/index.json
```
What to build:
1. One ASP.NET Core program, one module folder per area: `Rights`, `Registry` (models + skills), `Approvals`, `Audit`, plus `Platform` (sign-in, errors, outbox publisher, Kafka consumer, health). One EF Core `DbContext`, one migrations folder.
2. Configuration only from environment variables (names in section 8); never a value in the repo. `migrate` argument = apply migrations and exit.
3. Tests (xUnit): every route (allowed, refused, bad input), the rights rules, tier → right, manifest validation, idempotent consumer, retries → DLQ (with a fake Kafka client), outbox (saved together, published once), the append-only and no-delete triggers (database tests against `controlcentre_test`, connection from `~/.config/ooh/control-centre-test.env`, written by `install/59-control-centre-databases.sh`; setup and migrations as the test owner role, every test as `controlcentre_test_app`, except the trigger test, which runs as the test owner to prove the trigger itself refuses; the app-role test proves "permission denied"). Tokens in tests are signed by a test key; no real Keycloak, Kafka or model.
4. `Dockerfile`: multi-stage, the pinned images in section 4, runs as non-root, listens on 8080, read-only root filesystem works.
5. `services/control-centre/README.md`: Quick Guide (build, test, run the migrations locally against the test database).
6. Any other dependency: Part A names it in its report with an exact version and one line why; none may be added without that.

Part A done when: `dotnet format --verify-no-changes`, `dotnet build -warnaserror` and `dotnet test` pass (database tests included once the test database exists); `uv run --project contracts/check pytest` passes.

### Part B — Getting it running (branch `stage-1-part-b`, Codex B, tile 1)

Files (only these):
```
.github/workflows/control-centre-image.yml
deploy/apps/control-centre/*.yaml                  (Deployment with init container, Service, ConfigMap, Ingress for admin. /api)
deploy/platform/postgres/db-controlcentre.yaml     (2 Databases + 4 DatabaseRoles: controlcentre, controlcentre_app, controlcentre_test, controlcentre_test_app)
deploy/platform/kafka/users/control-centre.yaml
deploy/platform/kafka/users/ooh-stage-check.yaml
deploy/platform/placeholders/admin-ingress.yaml    (admin. keeps only "/"; "/api" moves to deploy/apps)
deploy/platform/placeholders/control-centre-api.yaml   (marked retired at the top; no longer applied)
deploy/platform/keycloak/realm-ooh.yaml            (device sign-in on ooh-admin-console, for fresh installs)
install/30-platform-apply.sh                       (stop applying the control-centre-api placeholder; nothing else changes)
install/35-realm-sync.sh                           (also switch device sign-in on for ooh-admin-console; never creates a client)
install/40-check-platform.sh                       (admin. /api: when the control-centre Deployment exists, GET /api/rights/me?user_id=x → 401; otherwise the placeholder page)
install/59-control-centre-databases.sh
install/60-control-centre-secrets.sh
install/61-control-centre-deploy.sh
install/62-check-control-centre.sh
contracts/identity.md                              (add the ooh-stage-check principal; device sign-in on ooh-admin-console)
docs/ARCHITECTURE.md                               (the Control Centre keeps its own change log; the Audit writer keeps the full trail across services. The storage text is NOT changed in Stage 1)
README.md
```
What each does:
- Workflow: on push to any branch when `services/control-centre/**` or the workflow changes, and on demand (`workflow_dispatch`, for merge commits the path filter misses): build with the Dockerfile in `services/control-centre`, push `ghcr.io/frozenfussion/ooh-control-centre:<first 12 characters of GITHUB_SHA>`, with the label `org.opencontainers.image.source=https://github.com/frozenfussion/open-office-harness` so the package is linked to the repo. Nothing else (no `latest` tag).
- `59-control-centre-databases.sh` (no sudo): creates the four role password Secrets if missing (generated, never printed), then applies `db-controlcentre.yaml`, waits for both databases, and writes `~/.config/ooh/control-centre-test.env` (mode 600) with the test owner and test app connection strings (test database only, never the live one; accepted exception, section 14). The host is the ClusterIP of `ooh-pg-rw` (verified 09 Nov: the Droplet itself can reach it; nothing is opened to the outside). Re-runnable.
- `60-control-centre-secrets.sh` (no sudo): applies the two KafkaUsers, waits until Strimzi has made their passwords, then puts what the Control Centre needs into `ooh-apps` (Secret `control-centre-db` with keys `connection` (app role) and `migrate-connection` (owner role), Secret `control-centre-kafka` with key `password`) without printing; never overwrites; re-runnable.
- `61-control-centre-deploy.sh` (no sudo, run from the `stage-1` worktree): takes the image tag (default: `git rev-parse --short=12 HEAD`), checks the image exists on ghcr.io (if not: `STOP: image not built yet; run the workflow for this commit`), re-applies `deploy/platform/placeholders/admin-ingress.yaml` (now `/` only), applies `deploy/apps/control-centre/`, waits for the init container and the new pod revision to be Ready, then removes the `control-centre-api` placeholder Deployment and Service (they hold no data). Re-runnable. The new Ingress uses `secretName: admin-tls` and has **no** cert-manager annotation (the existing `admin` Ingress already manages that certificate).
- `62-check-control-centre.sh` (no sudo): the checks in section 2 item 3, one `PASS`/`FAIL` line each. Service-account secrets are read inside the Keycloak pod into variables and sent to the token endpoint on standard input, never on a command line or printed. Kafka steps run in short-lived pods as `ooh-stage-check` that remove themselves. Device sign-in: prints the link and code, waits for Aziz.
- README Quick Guide: section 9.

Part B done when: every script passes `bash -n` and `shellcheck`; `kubeconform -strict` passes on all manifests; the workflow file is valid; Aziz has run 59 (the databases). The live run 60 → 61 → 62 happens **after the merge** into `stage-1` (section 14, change 6). On a fresh server the order is 30 → 59 → 60 → 61 → 40 → 62 (the README says so).

### Merge (after both Parts pass review)

Codex makes the branch `stage-1` from `stage-1-base` in a new worktree `~/projects/worktrees/stage-1`, merges both branches (the file lists do not overlap), runs every check in section 2 item 5 on a clean worktree, and writes `docs/STATUS.md` (the only file written at merge).

## 8. Fixed names between the Parts

| What | Value |
|---|---|
| Container port | 8080; probes `GET /health` |
| Image | `ghcr.io/frozenfussion/ooh-control-centre:<first 12 characters of the commit hash>`; init container args `["migrate"]` |
| Environment variables | `CC_DB_CONNECTION` (Secret `control-centre-db`, key `connection`, app role), `CC_DB_MIGRATE_CONNECTION` (same Secret, key `migrate-connection`, owner role; init container only), `CC_KAFKA_BOOTSTRAP` (`ooh-kafka-kafka-bootstrap.ooh-platform.svc:9092`), `CC_KAFKA_USERNAME` (`control-centre`), `CC_KAFKA_PASSWORD` (Secret `control-centre-kafka`, key `password`), `CC_OIDC_ISSUER` (`https://auth.faysalaziz.com/realms/ooh`), `CC_OIDC_AUDIENCE` (`ooh-control-centre`) |
| Kubernetes names | namespace `ooh-apps`; Deployment, Service and container `control-centre`; Service port 8080 |
| Test settings file | `~/.config/ooh/control-centre-test.env` with `CC_TEST_DB_MIGRATE_CONNECTION=...` (test owner) and `CC_TEST_DB_CONNECTION=...` (test app role) |
| Image tag | first 12 characters of the commit hash, on GitHub and on harness |

## 9. README Quick Guide additions (in order, each with where to type it, which password, the good result)

1. Install the .NET tools in your home folder (section 3).
2. Make the databases: `install/59-control-centre-databases.sh`.
3. See the image build: the repo's Actions tab on GitHub (green tick = image ready). The first time only: do this on GitHub: the package `ooh-control-centre` → Package settings → Change visibility → Public (if it is not public already).
4. Secrets: `install/60-control-centre-secrets.sh`.
5. Deploy: `install/61-control-centre-deploy.sh` (what "waiting" looks like).
6. Check: `install/62-check-control-centre.sh`, including the browser sign-in step.
7. Everyday: Control Centre logs, restart, which image is running, what to do after a reboot.
8. Builder checks: `dotnet format`, `dotnet build`, `dotnet test`.
9. Every new `STOP:` and `FAIL` message and what to do.

## 10. Files that already exist (spec author's; Codex does not change them)

`AGENTS.md`, `CLAUDE.md`, `LICENSE`, `docs/specs/*`, `docs/plan/*`, `docs/images/*`, `install/01-server-setup.sh`, and every Stage 0 file not listed in Part A or Part B. If Codex believes one must change, it stops and asks Aziz with the reason.

## 11. Pre-mortem

| Step | Failure | How it shows | Action |
|---|---|---|---|
| Image build | push refused | Actions log: `denied` / 403 | the workflow needs `permissions: packages: write` |
| Image pull | `ImagePullBackOff` | `kubectl get pods -n ooh-apps` | the package is not public yet: switch it to Public once (README step 3) |
| Kafka client in chiseled image | crash at start: native library cannot load | pod log | switch the run image to `mcr.microsoft.com/dotnet/aspnet:10.0.14-noble` (still non-root), record it as a deviation |
| Tokens | every call 401 | pod log: issuer or signing keys not fetched | the pod must reach `https://auth.faysalaziz.com` (same Droplet, through Traefik); if it cannot, the spec author decides |
| Migrations | init container fails | `kubectl logs -c migrate` | read the error; never edit an applied migration, add a new one |
| Strimzi secret | `control-centre` Kafka secret missing | 60 prints `STOP` | wait for the KafkaUser to be Ready, re-run 60 |
| Device sign-in | "client not allowed" | 62 prints `FAIL device sign-in` | run `install/35-realm-sync.sh`, then 62 again |
| Outbox | messages sent twice after a restart | duplicate `event_id` on the topic | allowed: consumers ignore duplicates; never a missing message |

## 12. UNVERIFIED (each script stops with a clear message if wrong)

1. Confluent.Kafka's native library inside the chiseled image (fallback in section 11).
2. The pod reaching `auth.faysalaziz.com` through the Droplet's own public address (Stage 0 proved it from the host, not from a pod).
3. The exact full commit SHAs of the four GitHub actions: Part B reads them from each release on the day and names them in its report.
4. Whether the first image pushed by `GITHUB_TOKEN` is public straight away or needs the one-time switch to Public (README step 3).
5. Whether the path filter starts a build for the `stage-1` merge commit; if not, the workflow is run on demand for it.

## 13. Out of scope for Stage 1

The Admin Console screens, the Harness, the Model Gateway, DLQ view and replay, sign-up approvals, the Audit writer and the cross-service audit trail, Helm, monitoring and tracing, backups, AWS. Codex does not pre-build any of it.

## 14. Changes agreed during the build — these override the sections above

| # | Change | Who / when |
|---|---|---|
| 1 | Spec review by Claude Code before the builders started (30 findings, `reviews/stage-1-spec-review` in the course folder) folded into the sections above: two database roles, tokens and secrets on standard input only, safe audit check with rollback, fixed check data, outbox message fields, business vs. system tables, no test exception in triggers, Ingress certificate reuse, 12-character image tag, named test dependencies | Spec author + reviewer, 09 Nov 20:48–21:10 |
| 2 | **Accepted exception to "secrets only in Kubernetes Secrets":** `~/.config/ooh/control-centre-test.env` (mode 600) holds the **test** database's connection strings so the builders' tests can run on harness. Never the live database | Aziz, 09 Nov 20:59 |
| 3 | The file-storage contract (`contracts/storage.md`, the storage paragraph of `docs/ARCHITECTURE.md`) still says Spaces; it is rewritten for the `ooh-files` volume in the stage that builds the Harness, which is the first user of file storage. The global rules already say `ooh-files` | Aziz, 09 Nov 20:59 |
| 4 | Device sign-in on `ooh-admin-console` is switched off again in Stage 4 (Admin Console) | Spec author, 09 Nov 21:10 |
| 5 | Re-review (8 new findings from the fixes, `reviews/stage-1-spec-rereview` in the course folder) folded in: audit check proves both "permission denied" (app role) and the trigger (owner); approvals counted by polling, no consumer-lag read; paging by `(created_at, id)`; fields for messages the program sends on its own; folders and tag for testing before the merge | Spec author + reviewer, 09 Nov 21:12 |
| 6 | Part B ends with static checks only. The live run 60 → 61 → 62 happens after Codex merges both Parts into `stage-1`: the image workflow (Part B) and the Control Centre code (Part A) are on different branches, so no image can exist before the merge. Pushing `stage-1` builds the image; 61 gets that 12-character tag | Spec author, 09 Nov 21:53 (found when Codex B asked for Part A's image tag) |
| 7 | Part A review decisions: `people` written and audited only when new or changed, race-safe insert, `last_seen_at` refreshed at most hourly without an audit row; Kafka send timeout 10 s; a new migration aligns the schema with EF's names (applied migrations never edited); Microsoft.Testing.Platform kept (deviation recorded); messages failing schema checks go straight to the DLQ, retries only for passing errors; `/api/admin/models` sorted by (purpose, tier, role, id) without paging, `/api/admin/people` and `/api/admin/rights` page with `after=`; `DOTNET_EnableDiagnostics=0` for the read-only filesystem | Spec author, 09 Nov 21:58 (`reviews/stage-1-part-a-fixes`) |
| 8 | Part B review decisions: manifests use the Stage 0 placeholders from `deploy/values/do.env`; check (i) reads only this run's audit messages (item 3i reworded); liveness = TCP on 8080, readiness = `/health`; stale `stage.check` approvals are rejected through the API at the start of check (g); 60 stops if Strimzi's Kafka password changed instead of overwriting | Spec author, 09 Nov 22:24 (`reviews/stage-1-part-b-fixes`) |
| 9 | Live-run fixes (found when Aziz ran 61 and 62): the program reads `ASPNETCORE_` settings so it listens on 8080 (it had fallen back to localhost:5000); Npgsql GSS encryption is disabled for all connections because the chiseled image has no Kerberos library; client secrets are passed to Keycloak without a trailing newline; the check's device sign-in sends a PKCE S256 challenge (the client requires S256 for every flow) and prints the complete sign-in link so it can be opened directly | Spec author, 09 Nov 22:51–23:26 |
| 10 | `install/62-check-control-centre.sh` uses tier 99 for its check data, so it never collides with real models Aziz adds from Stage 2 on (changed by Stage 2 Part D) | Spec author, 10 Nov 14:00 (Stage 2 spec review) |
