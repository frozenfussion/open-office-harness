# Stage 1 — Control Centre (rights, registries, approvals, its own audit)

Written 2026-11-09 by Claude (orchestrator). Read `00-GLOBAL-RULES.md` first; it applies in full.
**Base commit:** `main` right after this spec is merged. Before any Part starts, Codex tags that commit `stage-1-base` and pushes the tag (`git tag -a stage-1-base -m "Stage 1 base" && git push origin stage-1-base`). Every Part starts from that tag.
**Tag when accepted:** `spine-v0.1`.

## 0. Aziz's words and decisions (Malaysia time)

- 07 Nov 16:26: Rights are fixed rules in the Control Centre, never decided by an AI; the classifier only suggests.
- 08 Nov 12:00: A tier is a field on each chat model entry; creating a tier creates its right.
- 08 Nov: Sign-ups go through Approvals like every other human decision (later stage).
- 09 Nov 16:18: "Do not unnecessarily add a tech stack." Always the simplest step that does not cut corners.
- 09 Nov 20:07: GitHub builds the Docker images: "Yes, I agree."
- 09 Nov 20:19: Stage 1 is split by code vs. getting it running: "Yes, I do." Builders: Codex (GPT-6.1-Sol, medium, fast). Checks and reviews: Claude Code.

## 1. Purpose

Replace the placeholder at `https://admin.faysalaziz.com/api` with the real **Control Centre**: one C# program (modular monolith) that
- answers **rights checks** with fixed rules (fail closed);
- keeps the **model registry** (which model serves which purpose and tier) and the **skill registry** (skill manifests);
- receives **approval requests** from Kafka, lets an admin decide them, and publishes the decision to Kafka;
- records **its own audit trail** (every change it makes), append-only and enforced by the database, and publishes each record to `audit.events`.

No AI model is called. No user interface (the Admin Console is Stage 4). No DLQ view or replay (deferred, as `contracts/identity.md` says).

## 2. Done when (all of these)

1. GitHub Actions builds the image `ghcr.io/frozenfussion/ooh-control-centre:<git short hash>` on every push that changes `services/control-centre/`, the run is green, and the image can be pulled **without logging in** (public).
2. On harness, Aziz runs `install/59-control-centre-databases.sh`, `install/60-control-centre-secrets.sh` and `install/61-control-centre-deploy.sh`; each ends with `DONE`. The pod in `ooh-apps` is Ready; the database migrations ran in the init container; the `control-centre-api` placeholder Deployment and Service are gone.
3. `install/62-check-control-centre.sh` prints `PASS` for every line and ends with `DONE`. Aziz signs in once in his browser during the run (device sign-in, section 7). It checks:
   a. `GET https://admin.faysalaziz.com/api/rights/me?user_id=x` without a token → 401;
   b. a valid token from realm `ooh` that does not carry audience `ooh-control-centre` → 401 (Part B names the client it uses in its report);
   c. as the Harness service account: `POST /api/rights/check` for a new test user id (`stage-check-<random>`) with no grants → `allowed:false`, `decided_by:"no-grant"`;
   d. as the Model Gateway service account: `GET /api/models?purpose=classification` → 200 (a list); as the Harness service account the same call → 403;
   e. as Aziz (admin): create a chat model entry with tier 2 (model_id `stage-check`) → the right `chat.tier.2` now exists; grant it to the test user; the Harness service account's rights check for that user and tier → `allowed:true`; remove the grant → `allowed:false`; remove the check's model entry again at the end, so no fake model stays active in the registry;
   f. as Aziz: register the Slides skill from `contracts/skills/slides/manifest.json` (re-running is harmless); `GET /api/skills?user_id=<test user>` lists it only after `skill.slides` is granted;
   g. a check principal publishes an `approval.requested` event (action `stage.check`) to `approvals.requested` **twice with the same event_id** → exactly one pending approval appears;
   h. as Aziz: approve it → an `approval.decided` event with the same `correlation_id` is read back from `approvals.decided`;
   i. the Control Centre's audit query shows the grant, the model entry, the skill and the decision, and matching `audit.event` messages are read back from `audit.events`;
   j. an `UPDATE` and a `DELETE` on the audit table, run as the Control Centre's own database role, are both refused by the database.
4. After `sudo reboot`, `install/40-check-platform.sh` and `install/62-check-control-centre.sh` pass again without anyone touching the server (allow 5 minutes).
5. In a clean worktree of `stage-1`: `dotnet format --verify-no-changes`, `dotnet build -warnaserror` and `dotnet test` pass in `services/control-centre`; `uv run --project contracts/check pytest` passes; `bash -n` and `shellcheck` are clean for every file in `install/`; `kubeconform -strict` passes on `deploy/`.
6. `README.md` Quick Guide covers everything in section 9; `docs/STATUS.md` says Stage 1 is done and lists what was checked.

## 3. Prerequisites (before the builders start)

1. **.NET SDK on harness, in Aziz's home folder (no sudo).** Claude types this into the Shell tile; Aziz presses Enter:
   `curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh && bash /tmp/dotnet-install.sh --version 10.0.403 --install-dir ~/.dotnet && grep -q DOTNET_ROOT ~/.bashrc || printf '\nexport DOTNET_ROOT=$HOME/.dotnet\nexport PATH=$HOME/.dotnet:$HOME/.dotnet/tools:$PATH\nexport DOTNET_CLI_TELEMETRY_OPTOUT=1\n' >> ~/.bashrc; source ~/.bashrc && dotnet --version`
   Good result: `10.0.403`. Codex sessions started before this need `source ~/.bashrc`.
2. **Databases** (Part B writes the script first, Aziz runs it before Part A runs database tests): `install/59-control-centre-databases.sh` (section 7, Part B). Until then Part A runs only the tests that need no database and says so in its report.

## 4. Decisions for this stage (fixed; versions verified 09 Nov 2026 from dotnet release metadata, nuget.org, mcr.microsoft.com and GitHub releases)

| Item | Decision | Why |
|---|---|---|
| Runtime | .NET **10.0.14**, SDK **10.0.403**, ASP.NET Core minimal APIs | .NET 10 is the long-term release (to Nov 2028); .NET 11 is only a release candidate |
| Data | EF Core **10.0.14** + Npgsql.EntityFrameworkCore.PostgreSQL **10.0.3**; EF Core migrations only | Global rules |
| Tokens | Microsoft.AspNetCore.Authentication.JwtBearer **10.0.14** | Microsoft's own OIDC/JWT validation |
| Kafka | Confluent.Kafka **2.16.0**, SCRAM-SHA-512 on the internal listener 9092 | The standard .NET Kafka client |
| Tests | xunit.v3 **4.0.3**, Microsoft.NET.Test.Sdk **18.11.0** | Global rules say xUnit |
| Images | build: `mcr.microsoft.com/dotnet/sdk:10.0.403-noble`; run: `mcr.microsoft.com/dotnet/aspnet:10.0.14-noble-chiseled` | Official Microsoft images on Ubuntu 24.04; chiseled = small, no shell, non-root |
| Image build | GitHub Actions, `.github/workflows/control-centre-image.yml`; actions pinned by full commit SHA: actions/checkout v7.0.1, docker/setup-buildx-action v4.4.1, docker/login-action v4.8.0, docker/build-push-action v7.4.0; login with the workflow's own `GITHUB_TOKEN` (`packages: write`, `contents: read`) | Free for a public repo; nothing added to the Droplet; the image inherits the repo's public visibility |
| Database | `controlcentre` (owner role `controlcentre`) and `controlcentre_test` (owner role `controlcentre_test`) on `ooh-pg`, made by CloudNativePG `Database` + `DatabaseRole` resources, reclaim policy retain | Each service owns its database; tests never touch the live one |
| Migrations | the same image run with the argument `migrate` as an init container: it applies pending migrations and exits; the main container never migrates | One writer of the schema, safe when there is more than one copy (EKS later) |
| Kafka user | `KafkaUser control-centre` with exactly the rights in `contracts/identity.md`; consumer group `control-centre` | Contract |
| Getting events out safely | an **outbox table** in `controlcentre`: a change, its audit row and its outgoing message are saved in one transaction; a background loop in the same program publishes unsent outbox rows and marks them sent | Without it a crash between "saved" and "published" loses a decision. No new technology: one table and one loop |
| Consumer rules | `approvals.requested`: ignore an `event_id` already handled (table `processed_events`); 3 tries with 1 s, 5 s, 15 s waits; then publish a `dlq.entry` to `dlq.approvals.requested` and move on | Global rules |
| Hostname | `admin.faysalaziz.com/api/*` → the Control Centre (the Ingress keeps the `/api` prefix); `/health` is only for Kubernetes probes, not public | Three-name design |
| People | the Control Centre knows a person by `user_id` (= Keycloak `sub`). Table `people` (user_id, email, name, first_seen_at, last_seen_at) is filled when a person's own token reaches the Control Centre or when an admin grants them something | No call to Keycloak's admin API needed |
| Admin sign-in for scripts | Keycloak's **device sign-in** (OAuth 2.0 Device Authorization Grant) switched on for the existing public client `ooh-admin-console`; the check script shows a link and code, Aziz signs in in his browser (like `gh auth login`); the token stays in a shell variable, never printed or saved | Lets Aziz act as admin before the Admin Console exists, with his own identity. Nothing new installed |
| Check principal | `KafkaUser ooh-stage-check`: write `approvals.requested`; read `approvals.decided` and `audit.events`; group `ooh-stage-check` only | The check needs to play the requester; it must not borrow a real service's identity |

## 5. Data model (Control Centre database `controlcentre`)

All business tables: UUID primary key, `created_at`, `updated_at`, `deleted_at`, `created_by`, `updated_by` (user_id or `system`). Times in UTC (`timestamptz`). "Remove" sets `deleted_at`; "restore" clears it. No hard delete: a statement trigger refuses `DELETE` and `TRUNCATE` on business tables (the test database owner may truncate business tables during test setup only, never `audit_log`).

| Table | Holds |
|---|---|
| `people` | user_id (unique), email, name, first_seen_at, last_seen_at |
| `rights` | key (unique, e.g. `chat.tier.2`, `skill.slides`, `image.generate`), description, source (`tier` / `skill` / `builtin`) |
| `grants` | right_key, subject_type (`user` / `everyone`), subject_id (user_id, or null for everyone). Unique among active rows |
| `model_entries` | the fields of the registry answer in `contracts/http/control-centre.openapi.yaml` (purpose, tier for chat only, role main/backup, location, api_type, endpoint_url, model_id, secret_ref = a Secret **name**, rate_limit_per_minute, daily_budget, health). At most one active `main` and one active `backup` per purpose + tier. `health` starts as `unknown` (the Gateway reports it from Stage 2) |
| `skills` | name (unique), version, manifest (jsonb, validated against `contracts/skills/manifest.schema.json`) |
| `approvals` | request event_id, correlation_id, requester user_id, producer, action, details, risk, requested_by, status (`pending` / `approved` / `rejected`), decided_by, note, decided_at |
| `processed_events` | event_id (primary key), topic, processed_at |
| `outbox` | topic, key (= correlation_id), envelope (jsonb), created_at, sent_at |
| `audit_log` | id (bigint identity), occurred_at, actor, action, target, outcome, detail (jsonb: before/after; secret values never stored), correlation_id. **Append-only:** a trigger refuses `UPDATE`, `DELETE` and `TRUNCATE` for every role, including the owner |

Built-in rights created by the first migration: `image.generate`. Creating a chat model entry with a new tier creates `chat.tier.<n>`; registering a skill creates the right named in its manifest. Rights are never removed automatically.

## 6. HTTP routes (all JSON; every route except `/health` needs a valid token with audience `ooh-control-centre`)

Who may call is decided by the token: **admin** = realm role `ooh-admin`; **Harness** = `azp` `ooh-harness-api`; **Gateway** = `azp` `ooh-model-gateway`; **self** = a user token whose `sub` equals the `user_id` in the request.

| Route | Who | Does |
|---|---|---|
| `GET /health` | anyone (probes) | `{"status":"ok"}` when the database answers, else 503 |
| `POST /api/rights/check` | Harness, admin, self | existing contract. `chat.tier` + target `"n"` → right `chat.tier.n`; `skill.use` + target skill name → the active skill's right; `image.generate` → `image.generate`. Allowed if an active grant exists for the user or for everyone. `decided_by`: `grant:user`, `grant:everyone` or `no-grant`. Unknown tier or skill → `allowed:false`. Any internal error → 503 (callers treat it as not allowed) |
| `GET /api/rights/me` | Harness, admin, self | existing contract |
| `GET /api/skills` | Harness, admin, self | existing contract: only active skills whose right the user holds |
| `GET /api/models` | Gateway only | existing contract |
| `GET /api/admin/people`, `GET /api/admin/people/{user_id}` | admin | people with their active grants |
| `GET /api/admin/rights` | admin | all rights |
| `POST /api/admin/grants`, `DELETE /api/admin/grants/{id}` | admin | grant a right to a user or to everyone; remove (sets `deleted_at`) |
| `GET/POST /api/admin/models`, `GET/PUT/DELETE /api/admin/models/{id}` | admin | the model registry (DELETE = remove) |
| `GET/POST /api/admin/skills`, `GET/PUT/DELETE /api/admin/skills/{name}` | admin | the skill registry (POST of an existing name with the same version changes nothing and returns 200) |
| `GET /api/admin/approvals?status=&limit=&before=`, `GET /api/admin/approvals/{id}` | admin | approvals, newest first |
| `POST /api/admin/approvals/{id}/decision` | admin | `{approved, note}`; only a pending approval (otherwise 409); saves the decision, its audit row and the outgoing `approval.decided` in one transaction |
| `GET /api/admin/audit?actor=&action=&target=&correlation_id=&before_id=&limit=` | admin | the Control Centre's own audit rows, newest first (limit 1–200, default 50). The full cross-service trail belongs to the Audit writer (Stage 3) |

Inputs are validated (unknown fields refused); lists use `limit` 1–200 (default 50); errors use the contract's `Error` shape. Every write appends an audit row and an outbox `audit.event` in the same transaction. Logs never contain request bodies or tokens. A user's own token reaching the Control Centre updates `people` (email and name from the token).

## 7. Parallel Parts

Two Codex windows at the same time, each in its own worktree from `stage-1-base`. **Rule: Part A changes no file Part B lists, and the reverse.** Nobody changes the files in section 10.

### Part A — Control Centre code (branch `stage-1-part-a`, Codex A, tile 0)

Files (only these):
```
services/control-centre/**                   (solution, projects, migrations, tests, Dockerfile, .dockerignore, README.md)
contracts/http/control-centre.openapi.yaml   (add every route in section 6; keep the existing four unchanged)
contracts/examples/http/control-centre.*     (one example per new route and status)
contracts/examples/index.json
```
What to build:
1. One ASP.NET Core program, one module folder per area: `Rights`, `Registry` (models + skills), `Approvals`, `Audit`, plus `Platform` (sign-in, errors, outbox publisher, Kafka consumer, health). One EF Core `DbContext`, one migrations folder.
2. Configuration only from environment variables (names in section 8); never a value in the repo. `migrate` argument = apply migrations and exit.
3. Tests (xUnit): every route (allowed, refused, bad input), the rights rules, tier → right, manifest validation, idempotent consumer, retries → DLQ (with a fake Kafka client), outbox (saved together, published once), the append-only and no-delete triggers (database tests against `controlcentre_test`, connection from `~/.config/ooh/control-centre-test.env`, written by `install/59-control-centre-databases.sh`). Tokens in tests are signed by a test key; no real Keycloak, Kafka or model.
4. `Dockerfile`: multi-stage, the pinned images in section 4, runs as non-root, listens on 8080, read-only root filesystem works.
5. `services/control-centre/README.md`: Quick Guide (build, test, run the migrations locally against the test database).

Part A done when: `dotnet format --verify-no-changes`, `dotnet build -warnaserror` and `dotnet test` pass (database tests included once the test database exists); `uv run --project contracts/check pytest` passes.

### Part B — Getting it running (branch `stage-1-part-b`, Codex B, tile 1)

Files (only these):
```
.github/workflows/control-centre-image.yml
deploy/apps/control-centre/*.yaml                  (Deployment with init container, Service, ConfigMap, Ingress for admin. /api)
deploy/platform/postgres/db-controlcentre.yaml     (Database + DatabaseRole for controlcentre and controlcentre_test)
deploy/platform/kafka/users/control-centre.yaml
deploy/platform/kafka/users/ooh-stage-check.yaml
deploy/platform/placeholders/admin-ingress.yaml    (admin. keeps only "/"; "/api" moves to deploy/apps)
deploy/platform/placeholders/control-centre-api.yaml   (marked retired at the top; no longer applied)
deploy/platform/keycloak/realm-ooh.yaml            (device sign-in on ooh-admin-console, for fresh installs)
install/30-platform-apply.sh                       (stop applying the control-centre-api placeholder; nothing else changes)
install/35-realm-sync.sh                           (also switch device sign-in on for ooh-admin-console; never creates a client)
install/40-check-platform.sh                       (admin. /api now expects the real service: 401 without a token)
install/59-control-centre-databases.sh
install/60-control-centre-secrets.sh
install/61-control-centre-deploy.sh
install/62-check-control-centre.sh
contracts/identity.md                              (add the ooh-stage-check principal; device sign-in on ooh-admin-console)
contracts/storage.md  docs/ARCHITECTURE.md          (Spaces → the ooh-files volume on the Droplet disk, as agreed 09 Nov)
README.md
```
What each does:
- Workflow: on push to any branch when `services/control-centre/**` or the workflow changes: build with the Dockerfile in `services/control-centre`, push `ghcr.io/frozenfussion/ooh-control-centre:<short sha>`. Nothing else (no `latest` tag).
- `59-control-centre-databases.sh` (no sudo): creates the two role password Secrets if missing (generated, never printed), then applies `db-controlcentre.yaml`, waits for both databases, and writes `~/.config/ooh/control-centre-test.env` (mode 600) with the test connection string. The host is the ClusterIP of `ooh-pg-rw` (verified 09 Nov: the Droplet itself can reach it; nothing is opened to the outside). Re-runnable.
- `60-control-centre-secrets.sh` (no sudo): applies the two KafkaUsers, waits until Strimzi has made their passwords, then puts what the Control Centre needs into `ooh-apps` (Secret `control-centre-db` with the connection string, Secret `control-centre-kafka` with the Kafka password) without printing; never overwrites; re-runnable.
- `61-control-centre-deploy.sh` (no sudo): takes the image tag (default: the short hash of `HEAD`), checks the image exists on ghcr.io, applies `deploy/apps/control-centre/`, waits for the init container and the new pod revision to be Ready, then removes the `control-centre-api` placeholder Deployment and Service (they hold no data). Re-runnable.
- `62-check-control-centre.sh` (no sudo): the checks in section 2 item 3, one `PASS`/`FAIL` line each. Service-account secrets are read inside the Keycloak pod into variables and sent to the token endpoint on standard input, never on a command line or printed. Kafka steps run in short-lived pods as `ooh-stage-check` that remove themselves. Device sign-in: prints the link and code, waits for Aziz.
- README Quick Guide: section 9.

Part B done when: every script passes `bash -n` and `shellcheck`; `kubeconform -strict` passes on all manifests; the workflow file is valid; then, with Part A's image: Aziz has run 59 → 60 → 61 → 62 on harness and 62 passes. On a fresh server the order is 30 → 59 → 60 → 61 (the README says so).

### Merge (after both Parts pass review)

Codex makes `stage-1` from `stage-1-base`, merges both branches (the file lists do not overlap), runs every check in section 2 item 5 on a clean worktree, and writes `docs/STATUS.md` (the only file written at merge).

## 8. Fixed names between the Parts

| What | Value |
|---|---|
| Container port | 8080; probes `GET /health` |
| Image | `ghcr.io/frozenfussion/ooh-control-centre:<short sha>`; init container args `["migrate"]` |
| Environment variables | `CC_DB_CONNECTION` (from Secret `control-centre-db`, key `connection`), `CC_KAFKA_BOOTSTRAP` (`ooh-kafka-kafka-bootstrap.ooh-platform.svc:9092`), `CC_KAFKA_USERNAME` (`control-centre`), `CC_KAFKA_PASSWORD` (Secret `control-centre-kafka`, key `password`), `CC_OIDC_ISSUER` (`https://auth.faysalaziz.com/realms/ooh`), `CC_OIDC_AUDIENCE` (`ooh-control-centre`), `CC_DISPLAY_TIMEZONE` (`Asia/Kuala_Lumpur`) |
| Kubernetes names | namespace `ooh-apps`; Deployment, Service and container `control-centre`; Service port 8080 |
| Test settings file | `~/.config/ooh/control-centre-test.env` with `CC_TEST_DB_CONNECTION=...` |

## 9. README Quick Guide additions (in order, each with where to type it, which password, the good result)

1. Install the .NET tools in your home folder (section 3).
2. Make the databases: `install/59-control-centre-databases.sh`.
3. See the image build: the repo's Actions tab on GitHub (green tick = image ready).
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
| Image pull | `ImagePullBackOff` | `kubectl get pods -n ooh-apps` | the package is not public: check its visibility on GitHub; it should inherit the public repo |
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

## 13. Out of scope for Stage 1

The Admin Console screens, the Harness, the Model Gateway, DLQ view and replay, sign-up approvals, the Audit writer and the cross-service audit trail, Helm, monitoring and tracing, backups, AWS. Codex does not pre-build any of it.

## 14. Changes agreed during the build — these override the sections above

| # | Change | Who / when |
|---|---|---|
| — | (none yet) | |
