# Stage 0 — Foundation (platform + repo skeleton + contracts)

Written 2026-11-08 by Claude (orchestrator). Read `00-GLOBAL-RULES.md` first; it applies in full.
**Base commit:** `main` right after this spec is merged (pull request #1). Before any Part starts, Codex tags that commit `stage-0-base` and pushes the tag (`git tag -a stage-0-base -m "Stage 0 base" && git push origin stage-0-base`). Every Part starts from that tag.
**Tag when accepted:** `spine-v0.0`.

## 0. Aziz's words and decisions (Malaysia time)

- 07 Nov 16:12 — "Everything separate." Product repo public (AGPL-3.0), course material private, participants use their own repos.
- 07 Nov 16:50 — No clicking in consoles for AWS: Terraform only. The base sandbox where the harness really runs is a DigitalOcean Droplet.
- 07 Nov 16:55 — Aziz sets up DigitalOcean by hand; he likes getting his hands dirty and expects participants to be able to do the same.
- 07 Nov 16:06 — Kafka only where it solves a real engineering problem.
- 08 Nov 12:50 — Hostnames on `faysalaziz.com`; gateway, Kafka and database internal only.
- 09 Nov 14:42 — "I don't like the name app. Let's call it harness."
- 09 Nov 14:56 — Three public names, all on the Droplet `harness`: `harness.` (Workspace + Harness API under `/api`), `admin.` (Admin Console + Control Centre API under `/api`), `auth.` (Keycloak). Aziz: "you have an exclusive yes to create the A records".
- 09 Nov 14:39 — Droplet `harness` created by Aziz, password login (no SSH keys).
- 08 Nov 12:50 — "Rehearse everything end to end, no surprises."
- 08 Nov 16:35 — "The entire work that we are going to do is the rehearsal." What goes to class is chosen afterwards.
- 08 Nov 18:03 — Claude has full authority for research; Aziz keeps the decisions.

## 1. Purpose

Turn an empty Droplet and an empty repo into a running, secure, **empty** platform that every later stage builds on without changing it:
k3s with HTTPS on all three hostnames, Kafka (KRaft) with the agreed topics, PostgreSQL, Keycloak with the `ooh` realm, object storage reachable — plus the repo skeleton and every contract between modules written down as files that a machine can check. No product code yet.

## 2. Done when (all of these, checked by Aziz on harness)

1. `install/40-check-platform.sh` prints `PASS` for every line and ends with `DONE`. It checks:
   a. all pods in `ooh-platform` and `cert-manager` are Ready;
   b. a valid Let's Encrypt (production) certificate on each of the three hostnames, `https://harness.faysalaziz.com/` and `https://admin.faysalaziz.com/` answer 200 (placeholder pages), `https://harness.faysalaziz.com/api/` and `https://admin.faysalaziz.com/api/` answer 200 (API placeholders), and `https://auth.faysalaziz.com/realms/ooh/.well-known/openid-configuration` answers 200 with `"issuer":"https://auth.faysalaziz.com/realms/ooh"`;
   c. a message produced to topic `ooh.smoke` by user `ooh-smoke` is read back by the same user, and the same user is **refused** when it tries to write to `skill.results`;
   d. every topic in section 6 exists with the partitions and retention given there;
   e. `SELECT 1` works against PostgreSQL as the `keycloak` role;
   f. a small text file written to the Spaces bucket under `checks/` can be read back.
2. Aziz can sign in at `https://auth.faysalaziz.com/realms/ooh/account` as the first admin created by `install/50-first-admin.sh`.
3. After `sudo reboot`, item 1 passes again without anyone touching the server (allow 5 minutes).
4. In a clean worktree of `stage-0`: `uv run --project contracts/check pytest` passes; `bash -n` and `shellcheck` are clean for every file in `install/`; `kubeconform -strict` passes on `deploy/platform/` (CRDs skipped are listed in the report).
5. `README.md` starts with a Quick Guide covering everything in section 9.
6. `docs/STATUS.md` says Stage 0 is done and lists what was checked.

## 3. Prerequisites — Aziz by hand, before Part B is tested (Part A does not need them)

Claude gives these to Aziz one step at a time; they go into the instructor runbook.
1. **Droplet** `harness` (done 09 Nov): Ubuntu 24.04.5 LTS, 143.198.221.2, user `aziz` with sudo, password login.
2. **Cloud firewall** on `harness`: inbound TCP 22, 80, 443 only. Everything else denied (the Kubernetes API on 6443 is not public).
3. **DNS** (done 09 Nov): A records `harness`, `admin`, `auth` on `faysalaziz.com` → 143.198.221.2.
4. **Spaces**: bucket `ooh-files` in SGP1 (private, no CDN) and an access key limited to that bucket. Key values are typed into `install/20-platform-secrets.sh` only.
5. **Server setup**: tmux session `harness`; clone the repo to `~/projects/open-office-harness`; run `sudo install/01-server-setup.sh` (installs git, gh, tmux, fail2ban, Node 26, k3s, kubectl access for `aziz`, kubeconform, uv); `gh auth login` + `gh auth setup-git` + git name/email; Claude Code and the Codex CLI as user `aziz`, each signed in.
6. **Local settings file** (never in the repo): `~/.config/ooh/do.env`, made from `install/ooh.env.example` (Part B writes the example). Holds non-secret values that are personal or deployment-specific (the Let's Encrypt contact email, the Spaces region and bucket).

## 4. Decisions for this stage (fixed; versions verified 08 Nov 2026)

| Item | Decision | Why |
|---|---|---|
| OS | Ubuntu 24.04 LTS | k3s documents 24.04; 26.04 is not yet listed by k3s |
| Kubernetes | k3s **v1.36.6+k3s1** (single server), its built-in Traefik as the front door, its local-path storage | CloudNativePG 1.30 supports Kubernetes 1.34–1.36; Strimzi 1.3.1 is tested on 1.32–1.37. 1.36 suits both |
| Certificates | cert-manager **v1.21.3**, Let's Encrypt via HTTP-01 through Traefik; `letsencrypt-staging` and `letsencrypt-prod` cluster issuers | Current supported release |
| Kafka | Strimzi operator **1.3.1**, Kafka **4.3.2**, KRaft, one dual-role node (`KafkaNodePool` with broker + controller), 20 Gi | Strimzi requires Kafka + KafkaNodePool for KRaft; one node is enough for rehearsal |
| Kafka access | one internal listener `9092`, SCRAM-SHA-512, `authorization: simple`; one `KafkaUser` per service (Stage 0 has only `ooh-smoke`) | Contract: each service has its own credentials and topic rights |
| PostgreSQL | CloudNativePG operator **1.30.0**, PostgreSQL **18** (operator default image for 1.30, pinned by tag in the manifest), cluster `ooh-pg`, 1 instance, 20 Gi | One database per service, made by `Database` resources as services arrive; Stage 0 makes only `keycloak` |
| Keycloak | Keycloak operator **26.8.2** (CRDs + operator from `keycloak/keycloak-k8s-resources` tag `26.8.2`), one instance, database `keycloak` on `ooh-pg` | Official operator; realm as a `KeycloakRealmImport` so it is in git |
| Object storage | DigitalOcean Spaces bucket `ooh-files` (S3 API) | Same code works with Amazon S3 in Stage 6 |
| Placeholder pages | `nginxinc/nginx-unprivileged` pinned by exact tag: four small Deployments — Workspace (`harness.` `/`), Harness API (`harness.` `/api`), Admin Console (`admin.` `/`), Control Centre API (`admin.` `/api`) — each page from a ConfigMap | Proves DNS, TLS and path routing now; replaced by the real service in its stage |
| Contracts | OpenAPI 3.1 (YAML) for HTTP, JSON Schema draft 2020-12 for events and skills | Readable by people and machines; a schema registry is a later lesson |
| Contract checks | Python 3.14 project in `contracts/check/` with `uv`; `jsonschema`, `openapi-spec-validator`, `pyyaml`, `pytest`, `ruff` at exact current versions | Proves every example matches its schema |

Exact download URLs for the operator manifests are written by Part B into `install/10-platform-operators.sh`. Before using one, the script checks it answers HTTP 200 and stops with `STOP: <url> not found` if not.

## 5. Parallel Parts

Two Codex windows at the same time, each in its own worktree from `stage-0-base` (global rules section 5).
**Rule: Part A changes no file Part B lists, and the reverse.** Nobody changes the files in section 8.

### Part A — Repo skeleton + contracts  (branch `stage-0-part-a`)

Files (only these):
```
.gitignore  .editorconfig
docs/ARCHITECTURE.md
contracts/README.md
contracts/identity.md
contracts/storage.md
contracts/http/control-centre.openapi.yaml
contracts/http/model-gateway.openapi.yaml
contracts/http/harness-api.openapi.yaml
contracts/events/envelope.schema.json
contracts/events/topics.yaml
contracts/events/payloads/skill.requested.schema.json
contracts/events/payloads/skill.result.schema.json
contracts/events/payloads/approval.requested.schema.json
contracts/events/payloads/approval.decided.schema.json
contracts/events/payloads/audit.event.schema.json
contracts/events/payloads/dlq.entry.schema.json
contracts/skills/manifest.schema.json
contracts/skills/slides/manifest.json
contracts/skills/slides/input.schema.json
contracts/skills/slides/output.schema.json
contracts/examples/**            (one valid example per schema and per HTTP request/response)
contracts/check/pyproject.toml  contracts/check/uv.lock
contracts/check/check_contracts.py
contracts/check/tests/test_contracts.py
```
What to write — the source is `docs/plan/MODULES-AND-CONTRACTS-v0.1.md` (sections C1–C9) and `docs/images/architecture-v0.2.png`:
1. `docs/ARCHITECTURE.md`: the modules table (what each owns, what it never does), the contracts in plain words, the flows (normal skill, skill with approval, tier routing, worker down), database ownership, deployment (Droplet now, EKS later). Embeds the architecture image. No model names.
2. `contracts/identity.md`: realm `ooh`; realm roles `ooh-admin`, `ooh-user`; clients `ooh-workspace` and `ooh-admin-console` (public, PKCE S256), `ooh-harness-api` and `ooh-control-centre` (confidential, service accounts); which token claims services read (`sub` = `user_id`, `realm_access.roles`); Kafka users and their topic rights as a table (rights for future services are listed but created in their stages).
3. HTTP contracts, exactly the routes in C2, C3, C4, C5 plus `GET /health` on each, plus `GET /api/models?purpose=&tier=` on the Control Centre (the Gateway reads the registry). Every request and response has a schema; every route except health declares bearer auth.
4. Event contracts: the envelope (C6) and one payload schema per event type (C7). `topics.yaml` = the table in section 6 of this spec, plus for each topic which event type it carries, who writes and who reads.
5. Skill contracts (C3): the manifest schema and the Slides skill's manifest, input and output.
6. `contracts/storage.md` (C9): key layout, signed links only, buckets never public.
7. `contracts/check/`: `check_contracts.py` validates every schema (draft 2020-12), every example against its schema, every OpenAPI file, and that every topic in `topics.yaml` names an existing payload schema. `tests/test_contracts.py` runs it and also proves one deliberately wrong example is rejected (kept inside the test, not as a file).
8. `contracts/README.md`: what each file is, and the versioning rule — a breaking change is a new version; the old one stays until nobody uses it.

Part A done when: `uv run --project contracts/check pytest` and `ruff check` / `ruff format --check` in `contracts/check` pass.

### Part B — Platform manifests + scripts  (branch `stage-0-part-b`)

Files (only these):
```
README.md
deploy/platform/namespaces.yaml
deploy/platform/cert-manager/cluster-issuers.template.yaml
deploy/platform/kafka/kafka.yaml            (Kafka + KafkaNodePool)
deploy/platform/kafka/topics/*.yaml          (one KafkaTopic per topic in section 6)
deploy/platform/kafka/users/ooh-smoke.yaml
deploy/platform/postgres/cluster.yaml
deploy/platform/postgres/db-keycloak.yaml    (Database resource + managed role)
deploy/platform/keycloak/keycloak.yaml
deploy/platform/keycloak/ingress.yaml
deploy/platform/keycloak/realm-ooh.yaml      (KeycloakRealmImport)
deploy/platform/placeholders/*.yaml          (ConfigMap + Deployment + Service per placeholder; Ingress for harness. and admin. with `/` and `/api` paths)
deploy/values/do.env                         (non-secret, non-personal values: domain, namespaces, sizes)
install/ooh.env.example
install/00-check-server.sh
install/10-platform-operators.sh
install/20-platform-secrets.sh
install/30-platform-apply.sh
install/40-check-platform.sh
install/50-first-admin.sh
```
What each does:
- `00-check-server.sh` (no sudo): k3s node Ready, `kubectl` works for `aziz`, `~/.config/ooh/do.env` present and complete, the three names resolve to this Droplet's public IP, ports 80/443 reachable from outside (via the public IP, not localhost).
- `10-platform-operators.sh` (no sudo): installs cert-manager, Strimzi (watching `ooh-platform`), CloudNativePG and the Keycloak operator (in `ooh-platform`) from pinned URLs; waits until each is Ready; re-runnable.
- `20-platform-secrets.sh` (no sudo): creates, only if missing, the Kubernetes Secrets: the `keycloak` database role password and the Keycloak bootstrap admin (both generated, never printed), and the Spaces access key and secret (typed by Aziz, hidden input). Never overwrites an existing secret; prints which it created and which already existed.
- `30-platform-apply.sh` (no sudo): renders `*.template.yaml` with values from `deploy/values/do.env` and `~/.config/ooh/do.env`, applies everything in `deploy/platform/` in order, waits for each to be Ready. Starts with `letsencrypt-staging`; switches the ingresses to `letsencrypt-prod` only after staging certificates are issued (protects against Let's Encrypt rate limits).
- `40-check-platform.sh` (no sudo): the checks in section 2 item 1, one `PASS`/`FAIL` line each, with a plain reason on fail; Kafka and PostgreSQL checks run in short-lived pods that remove themselves.
- `50-first-admin.sh` (no sudo): creates the first user in realm `ooh` with role `ooh-admin`; Aziz types the username, email and password (hidden); the password must be changed at first sign-in.
- Realm `ooh` (from `contracts/identity.md` content in section 5 Part A item 2 — Part B writes the realm from **this spec's** list, not from Part A's file): the four clients with redirect URIs on their hostnames, the two roles, self-registration **off** (sign-ups go through Approvals later), brute-force protection on, access token 5 minutes.
- Keycloak runs with `proxy.headers: xforwarded` behind Traefik; the operator's own ingress is off; our `ingress.yaml` serves `auth.faysalaziz.com` with a cert-manager certificate.
- Placeholder pages say: "open-office-harness · <Workspace | Admin Console | Harness API | Control Centre API> · arrives in Stage <N>". Plain HTML, no external fonts or scripts.
- `README.md`: the Quick Guide in section 9, then "What is where" and "Versions" tables.

Part B done when: every script passes `bash -n` and `shellcheck`; `kubeconform -strict` passes on all manifests (CRD kinds listed as skipped); Aziz has run scripts 00 → 50 on harness and `40-check-platform.sh` passes.

### Merge (after both Parts pass review)

Codex makes `stage-0` from `stage-0-base`, merges both Part branches (no conflicts expected — the file lists do not overlap), runs every check in section 2 item 4 on a clean worktree, and writes `docs/STATUS.md` (the only file written at merge).

## 6. Topics (fixed)

Single broker, so replication factor 1 and `min.insync.replicas` 1 (raised on AWS in Stage 6).

| Topic | Partitions | Retention | Carries |
|---|---|---|---|
| `skill.requests.slides` | 3 | 7 days | `skill.requested` |
| `skill.results` | 3 | 7 days | `skill.result` |
| `approvals.requested` | 3 | 30 days | `approval.requested` |
| `approvals.decided` | 3 | 30 days | `approval.decided` |
| `audit.events` | 3 | 30 days | `audit.event` |
| `dlq.skill.requests.slides` | 1 | 30 days | `dlq.entry` |
| `dlq.skill.results` | 1 | 30 days | `dlq.entry` |
| `dlq.approvals.requested` | 1 | 30 days | `dlq.entry` |
| `dlq.approvals.decided` | 1 | 30 days | `dlq.entry` |
| `dlq.audit.events` | 1 | 30 days | `dlq.entry` |
| `ooh.smoke` | 1 | 1 hour | platform checks only |

Topics are created only by `KafkaTopic` resources (auto-create off). A new skill adds its own `skill.requests.<skill>` and `dlq.skill.requests.<skill>` in its stage.

## 7. Order of work

**Part A** needs no server: it can run on harness or any machine with `uv`. Write, check, commit, report, stop.

**Part B:**
1. Write the manifests and scripts; run `bash -n`, `shellcheck`, `kubeconform`. Commit.
2. Stop and say: "Aziz, please run `install/00-check-server.sh`, then `install/10-platform-operators.sh`, as in README Quick Guide steps 3–4. Tell me what they print."
3. Then `20` → `30` → `40` → `50`, one at a time, each started by Aziz. Codex reads the output (and may use read-only `kubectl get/describe/logs`), fixes its files on the branch, and asks Aziz to re-run. Every failure and fix goes into the report's runbook section.
4. When `40-check-platform.sh` passes: commit, report, stop.

## 8. Files that already exist (written by the spec author; Codex does not change them)

- `AGENTS.md`, `CLAUDE.md`, `LICENSE`
- `docs/specs/00-GLOBAL-RULES.md`, `docs/specs/stage-0-foundation.md`
- `docs/plan/MODULES-AND-CONTRACTS-v0.1.md`, `docs/images/architecture-v0.2.png`
- `install/01-server-setup.sh`

If Codex believes one of these must change, it stops and asks Aziz with the reason.

## 9. README Quick Guide — must contain these steps, in this order, each with where to type it, which password it asks for, and the good result

1. What this is, in two lines, and where the Droplet runbook lives (the course's own notes; not in this repo).
2. Set up the server once: clone, `sudo install/01-server-setup.sh`, `gh auth login`, make `~/.config/ooh/do.env` from `install/ooh.env.example`.
3. Check the server: `install/00-check-server.sh`.
4. Install the operators: `install/10-platform-operators.sh`.
5. Create the secrets: `install/20-platform-secrets.sh` (what it asks for, and that it never shows secrets).
6. Apply the platform: `install/30-platform-apply.sh` (takes several minutes; what "waiting" looks like).
7. Check the platform: `install/40-check-platform.sh`.
8. Create the first admin: `install/50-first-admin.sh`, then sign in at the account page.
9. Everyday: see all pods (`kubectl get pods -A`), logs of one pod, restart one deployment, what to do after a reboot.
10. Run the checks a builder runs: contracts tests, `shellcheck`, `kubeconform`.
11. Every `STOP:` and `FAIL` message the scripts can print and what to do about it.

## 10. Pre-mortem — what can go wrong, how it shows, what to do

| Step | Failure | How it shows | Action |
|---|---|---|---|
| DNS | A record missing or not yet spread | `00-check-server.sh`: `FAIL harness.faysalaziz.com resolves to …` | Wait, re-check; certificates must not be requested before DNS is right |
| Firewall | 80 closed | certificates stay "pending"; HTTP-01 challenge fails | Cloud firewall must allow 80 and 443 from anywhere |
| Let's Encrypt | rate limit from repeated prod requests | cert-manager events say `rateLimited` | This is why staging comes first; wait for the limit window, do not loop |
| Operators | a pinned URL moved | `STOP: <url> not found` | Codex finds the correct URL for the same version on the vendor's release page and asks Aziz before changing the version |
| Strimzi | `Kafka` not Ready, node pool missing | `kubectl get kafka -n ooh-platform` shows `NotReady` | Check the KafkaNodePool roles and storage; one node needs both `broker` and `controller` |
| Memory | pods `OOMKilled` or `Pending` | `kubectl get pods -A` | Requests/limits too high or too low for 16 GB; adjust in the manifest, report it |
| CloudNativePG | cluster stuck in `Setting up primary` | `kubectl get cluster -n ooh-platform` | Storage class must be `local-path`; check operator logs |
| Keycloak | crash loop, database refused | pod logs: `password authentication failed` | The secret from step 20 and the managed role must match; re-run 20 (it never overwrites) only after checking names |
| Keycloak | sign-in redirects to `http://` or wrong host | browser | `proxy.headers: xforwarded` and hostname `https://auth.faysalaziz.com` |
| Spaces | `AccessDenied` | `FAIL storage` | The key must be limited to `ooh-files` with read and write |
| Reboot | checks fail in the first minutes | `FAIL` lines | Wait 5 minutes; then the logs of the failing pod |

Things that look wrong but are normal: the first certificate takes a minute or two; Strimzi takes several minutes to bring up Kafka the first time; `kubectl` prints warnings about deprecated fields in some vendor manifests.

## 11. UNVERIFIED (could not be checked from the spec author's machine; each script stops with a clear message if wrong)

1. The exact operator manifest file names in the cert-manager, Strimzi and CloudNativePG release assets (release pages exist and are current; asset lists were not readable). The Keycloak operator files at tag `26.8.2` answer HTTP 200.
2. The PostgreSQL 18 image tag that CloudNativePG 1.30.0 uses by default — Part B reads it from the operator's release notes and pins it.
3. The current exact versions of `jsonschema`, `openapi-spec-validator`, `pyyaml`, `pytest`, `ruff` — Part A pins what `uv` resolves on the day and names them in its report.
4. `install/01-server-setup.sh` on a real Droplet (it passes `bash -n` and `shellcheck`). The kubeconform asset name `kubeconform-linux-amd64.tar.gz` is the vendor's usual name.

## 12. Out of scope for Stage 0

Any product service, any database other than `keycloak`, Kafka users for future services, Helm charts, the Angular apps, the design fonts, monitoring and tracing, backups, AWS. Codex does not pre-build any of it.

## 13. Changes agreed during the build (09 Nov 2026) — these override the sections above

| # | Change | Who / when |
|---|---|---|
| 1 | Droplet is `harness` (143.198.221.2), password login; three public names `harness.`, `admin.`, `auth.` with each API under `/api` of its app's host | Aziz, 14:42–14:56 (already in sections 0–4) |
| 2 | Files are stored on the Droplet disk in a Kubernetes volume `ooh-files` (20Gi). **No DigitalOcean Spaces, no S3 server.** Prerequisite 4 (Spaces) is removed; the storage check writes and reads a file on that volume | Aziz, 16:18 |
| 3 | `00-check-server.sh` checks DNS, Traefik Ready and local HTTP/HTTPS answers only; reaching the server from outside is proven by the Let's Encrypt staging certificate in `30-platform-apply.sh` | Spec author, 15:55 |
| 4 | Generic skill events: `skill.requested` = `{skill, skill_version, input}`; `skill.result` = `{skill, status, output{file_key, mime, summary} or null, error{code, message} or null}` with status tied to output/error; each skill's own schemas live only under `contracts/skills/<skill>/` | Spec author (Part A review), 16:00 |
| 5 | `GET /api/models`: `tier` required only when `purpose=chat`. Registry answer: `model_entry_id, purpose, tier, role, location, api_type, endpoint_url, model_id, secret_ref` (Secret **name** only), `rate_limit_per_minute, daily_budget, health` | Spec author, 16:00 |
| 6 | Token audience = the client id of the API being called. Service accounts may pass a `user_id`; user tokens may not. Fifth client `ooh-model-gateway` (confidential, service account), whose tokens carry audience `ooh-control-centre`. The Control Centre client gets no Model Gateway audience | Spec author, 16:00 and 17:06 |
| 7 | `ooh.smoke` carries free-form test messages: no schema, no envelope | Spec author, 16:00 |
| 8 | Keycloak runs with `startOptimized: false` (stock image). If the Keycloak pod crash-loops on an old revision after a fix, delete that pod once | Build finding, 16:37–16:45 |
| 9 | Downloads in the scripts retry 5 times; only HTTP 404 is reported as "not found" | Build finding, 16:16 |
| 10 | Live realm changes go through `install/35-realm-sync.sh` (Keycloak's own admin CLI), because a realm import only creates a realm | Spec author, 17:06 |
| 11 | All volumes (Kafka, PostgreSQL, `ooh-files`) keep k3s's `local-path` storage class; `30-platform-apply.sh` patches each bound volume to reclaim policy **Retain** and `40-check-platform.sh` checks it — nothing is ever deleted. No extra StorageClass (Strimzi cannot change a node pool's storage class) | Spec author, 17:06, revised 17:55 |
| 12 | Codex permissions on the Droplet: "Approve for me" (sandbox on). Ubuntu 24.04 needs an AppArmor profile for `/usr/bin/bwrap` for the Codex sandbox to work | Aziz + Claude, 15:44–15:50 |
| 14 | PostgreSQL's first start creates the `keycloak` database and owner (the proven setting); `db-keycloak.yaml` also manages them declaratively | Spec author, 17:55 |
| 15 | `35-realm-sync.sh` only updates audience mappers of existing clients; it never creates a client (a missing client = STOP with the reason) | Spec author, 17:55 |
| 16 | The realm sync logs in **inside** the Keycloak pod with the pod's own `KC_BOOTSTRAP_ADMIN_*` settings; the password is never read on the Droplet. It does reach `kcadm.sh`'s command line inside that pod — accepted, because kcadm cannot read a password from stdin and the pod already holds it | Spec author, 18:10 |
| 13 | Cosmetics deferred to the apps stage: realm display name "Open Office Harness", branded sign-in page, no forced password change for an admin who set his own password | Aziz, 16:56 |
