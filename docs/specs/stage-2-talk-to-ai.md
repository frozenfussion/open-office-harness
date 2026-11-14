# Stage 2 — Talk to AI (Model Gateway, Harness API, Workspace chat, Admin Models & tiers)

Written 2026-11-10 by Claude (orchestrator). Read `00-GLOBAL-RULES.md` first; it applies in full.
**Base commit:** `main` right after this spec is merged. Before any Part starts, Codex tags that commit `stage-2-base` and pushes the tag (`git tag -a stage-2-base -m "Stage 2 base" && git push origin stage-2-base`). Every Part starts from that tag.
**Tag when accepted:** `spine-v0.2`.

## 0. Aziz's words and decisions (Malaysia time)

- 07 Nov 16:30: "Tier 1 is, I don't know, I'll make it DeepSeek or OpenAI. Tier 2 will be for more advanced users, and you will need rights for that. Say it will be Claude's API."
- 08 Nov 12:00: approved Models & tiers form: tier is a field (chat only; a new tier creates its right), main or backup, on-prem or cloud, API type (OpenAI-compatible, Anthropic Messages, OpenAI Responses), endpoint, model ID, **API key: stored encrypted, never shown again**, rate limit, daily budget.
- 10 Nov 13:32: "There's not going to be any hard code. I'm going to use DeepSeek, OpenAI, Anthropic's Claude… DeepSeek supports both [formats]. I might or might not do on-prem. It should all be adjustable and I should be able to add as many as I want in whichever tier I want from the admin or control centre." Rehearsal is the real build.
- 10 Nov 13:38: wants to see a screen and chat.
- 10 Nov 13:41: yes to four builders in parallel, Full Access for Codex, the faster plan (`plan/REHEARSAL-PLAN-v0.2.md` in the course folder): Stage 2 = Gateway + Harness API + Workspace chat + Admin Models & tiers.

## 1. Purpose

A signed-in person opens `https://harness.faysalaziz.com`, picks a chat tier they are allowed, types, and sees a real model's answer stream in word by word. An admin opens `https://admin.faysalaziz.com`, adds any number of models in any tier from any provider (OpenAI, Anthropic, DeepSeek, on-prem), types the API key once (stored encrypted, never shown again), and decides who may use each tier. **Nothing about providers is in code.**

Built in this stage:
- **Model Gateway** (Python, internal only): calls AI by purpose and tier, using the Control Centre's registry; three connection types; main then backup before the first word; per-user rate limit; daily budget; usage and cost recorded.
- **Harness API** (Python, `harness.faysalaziz.com/api`): conversations, streamed chat, rights checked against the Control Centre (fail closed), the user's allowed skills offered to the model as tools.
- **Workspace app** (Angular, `harness.faysalaziz.com/`): sign-in and the chat screen.
- **Admin Console app** (Angular, `admin.faysalaziz.com/`): sign-in and the Models & tiers screen, plus the Control Centre changes it needs (encrypted keys, prices, who may use a tier).

Not in this stage (section 13): skill jobs on Kafka, uploads and files, classifier routing, the other admin screens.

## 2. Done when (all of these)

1. GitHub Actions builds four new images on every push that changes their folder (and on demand): `ghcr.io/frozenfussion/ooh-model-gateway`, `ooh-harness-api`, `ooh-workspace`, `ooh-admin-console`, each tagged with the first 12 characters of the commit hash; the Control Centre image builds as before. All five pull without logging in.
2. On harness, from the merged `stage-2` worktree, these end with `DONE` (Claude runs them in tile 3 where Aziz watches; none needs sudo): `63-control-centre-keys.sh`, `61-control-centre-deploy.sh <tag>`, `64-model-gateway-setup.sh`, `65-model-gateway-deploy.sh <tag>`, `66-harness-api-setup.sh`, `67-harness-api-deploy.sh <tag>`, `68-workspace-deploy.sh <tag>`, `69-admin-console-deploy.sh <tag>`, `35-realm-sync.sh`. All pods in `ooh-apps` are Ready; the four placeholder pages are gone.
3. In the browser, Aziz signs in to the Admin Console, adds at least one chat model of each connection type with its real key (OpenAI-compatible, OpenAI Responses, Anthropic Messages), sets who may use each tier, and the keys never appear again anywhere (form, list, network responses, logs).
4. `install/70-check-stage-2.sh` prints `PASS` for every line and ends with `DONE` (section 9).
5. In the browser, Aziz signs in to the Workspace, picks a tier, asks a question, and the answer streams in word by word; the meta line under the answer shows the tier, the model's title and the token counts; reloading the page shows the conversation.
6. After `sudo reboot`, `40-check-platform.sh`, `62-check-control-centre.sh` and `70-check-stage-2.sh` pass again without anyone touching the server (allow 5 minutes), and the browser chat works.
7. In a clean worktree of `stage-2`: every Part's checks (section 7) pass; `uv run --project contracts/check pytest contracts/check/tests` passes; `bash -n` and `shellcheck` are clean for every `install/*.sh`; `kubeconform -strict` passes on `deploy/`.
8. `README.md` Quick Guide covers section 10; `docs/STATUS.md` says Stage 2 is done and lists what was checked.

## 3. Prerequisites (before the builders start)

1. Two more tmux tiles: tile 4 "CODEX C — builds" and tile 5 "CODEX D — builds" (Claude adds them; tiles 0–3 keep their numbers and roles).
2. Databases for the builders' tests: Part A writes `install/64-model-gateway-setup.sh` first and Part B writes `install/66-harness-api-setup.sh` first; Claude runs each as soon as it is pushed (no sudo). Until then those Parts run only the tests that need no database and say so.
3. Node 26 and the Angular CLI run through `npx` inside each app folder (Node 26 is already on harness); nothing is installed system-wide.

## 4. Decisions for this stage (fixed; versions checked 10 Nov 2026 on pypi.org, npmjs.com, Docker Hub and endoflife.date)

| Item | Decision | Why |
|---|---|---|
| Python services | Python **3.14.10**; image `python:3.14.10-slim-trixie` (build and run, non-root user `10001`); `uv` 0.13.7 for packages and lock files | Global rules; newest 3.14 patch (25 Oct 2026) |
| Web framework | FastAPI **0.162.2**, uvicorn **0.54.0**, pydantic **2.14.3** (comes with FastAPI, pinned) | Standard async Python API stack; streaming responses built in (no extra SSE package) |
| Outgoing HTTP | httpx **0.28.1** (provider calls with streaming, Control Centre and Gateway calls) | One client for sync and streaming calls |
| Database | PostgreSQL through psycopg **3.3.8** with its binary package `psycopg[binary]` (no system libpq) | Plain SQL; no ORM needed for a few tables |
| Migrations | numbered SQL files (`migrations/0001_*.sql`) applied in order by the program's own `migrate` command, recorded in a `schema_migrations` table; run by an init container as the owner role, exactly as the Control Centre does | Same proven pattern; no migration framework needed |
| Tokens | PyJWT **2.15.1** with `cryptography` **50.0.2** (`pyjwt[crypto]`), checking signature (realm keys, cached), issuer, audience, expiry, `sub` | Same checks as the Control Centre |
| Tests | pytest **9.2.0**; anyio's pytest plugin (comes with FastAPI) for async tests; respx **0.23.1** to fake provider and Control Centre answers; ruff **0.17.4** | Global rules: pytest, ruff; never a real model in tests |
| Web apps | Angular **22.2.5** (`@angular/core` and friends), Angular CLI **22.2.6** (`@angular/build`), TypeScript **6.0.3** (Angular 22.2 needs >=6.0 <6.1), rxjs **7.8.2**; the CLI's own `ng build` and `ng test` | Global rules; newest Angular 22 |
| Sign-in in the web apps | angular-auth-oidc-client **22.0.2**: authorization code + PKCE S256, silent refresh with refresh tokens, no tokens in local storage beyond what the library keeps in session storage | Certified OIDC client; supports Angular 22 (peer >=20) |
| Web app images | build: `node:26` slim image pinned by the builder to an exact tag and reported; run: `nginxinc/nginx-unprivileged:1.28.0-alpine` (already proven in Stage 0), port 8080, read-only root with `/tmp` and nginx cache as `emptyDir` | Static files; same server as the placeholders |
| Web app settings | each app reads `/config.json` at start (issuer, client id, API base `/api`) served from a ConfigMap; nothing about the domain is compiled in | Same image on Droplet and AWS |
| Design | `apps/design-system/` (tokens, component CSS, WordRain script, fonts, OFL licences) is copied into each app at build time; screens follow `docs/design/screens/Main.html`, `SignIn.html`, `AdminModels.html`. Both are spec-author files: the Parts read them, never change them | Global rules: design tokens from the Open Office Harness design system only |
| Connection types (`api_type`) | exactly three are supported by the Gateway: `openai_chat_completions`, `openai_responses`, `anthropic_messages`. Any other value in the registry is skipped by the Gateway (logged as "unsupported connection type"). The Control Centre keeps `api_type` a free string so the Stage 1 check data (`stage-check`) still works; the Admin Console offers only the three | Aziz 13:32: OpenAI format and Anthropic format; DeepSeek speaks both; OpenAI's newest models need Responses for tool calls, while chat completions stays for every other OpenAI-compatible service; the admin picks per entry |
| Provider keys | typed in the Admin Console form; the Control Centre encrypts them with AES-256-GCM (.NET's built-in `AesGcm`), the 32-byte encryption key from Secret `control-centre-keys` (key `encryption-key`, made by `63`); stored as `v1:<nonce>:<ciphertext>:<tag>` in base64; never returned to admins (`has_key` only); only the Gateway service account may read a decrypted key, through `GET /api/models/{id}/key`, inside the cluster | Aziz's approved form; replaces the Stage 0 "secret_ref = Kubernetes Secret name" choice; one owner of registry data |
| Who calls what (all with Keycloak service-account tokens, client credentials) | Harness → Control Centre (aud `ooh-control-centre`) and → Gateway (aud `ooh-model-gateway`); Gateway → Control Centre (aud `ooh-control-centre`). These audiences already exist in the realm | No realm audience change |
| In-cluster addresses | Control Centre `http://control-centre.ooh-apps.svc:8081` for the Gateway-only routes (registry, key) and `:8080` for everything else, Gateway `http://model-gateway.ooh-apps.svc:8080` (no Ingress for the Gateway). The Control Centre already serves `/api/...` paths on its own port | Gateway has no public name (fixed) |
| Rate limit | per model entry and per user: the Gateway counts this user's usage rows for that entry in the last 60 s; at `rate_limit_per_minute` the entry is skipped for this call | Approved form ("rate limit per user") |
| Daily budget | per model entry: the sum of today's cost (UTC day) from the Gateway's usage rows; at or above `daily_budget` the entry is skipped. `daily_budget` 0 = no limit | Approved form; 0 keeps the Stage 1 check data valid |
| Cost | `input_tokens × input_price_per_million / 1 000 000 + output_tokens × output_price_per_million / 1 000 000`, prices typed per model entry in USD; 0 when the prices are 0 (on-prem) | Prices are data, never code |
| Failover | entries for the purpose and tier are tried main first, then backup; a failure **before the first output** (connection error, timeout, non-2xx) moves to the next entry; after the first output a failure ends the answer with a `failed` event (no gluing of half answers) | Proven in HOORA AI |
| Budget fallback (Harness) | if every entry of tier N > 1 is over budget, the Harness answers with the lowest tier the user may use and says so in the meta line ("tier 2 is over its daily budget; answered with tier 1") | Approved form: "Over budget: tier 2 falls back to tier 1" |
| Skills as tools | the Harness offers the model only the skills the user may use (`GET /api/skills?user_id=`), each as a tool whose input schema is the skill's `input.schema.json` (copied into the Harness package, a test checks the copy equals `contracts/skills/<skill>/input.schema.json`). If the model calls a tool, the Harness answers with the fixed sentence `I would use the <title> skill for this. Skills are switched on in the next stage.` | Skills run on Kafka in Stage 3; the tool offer and rights work now |
| Conversation memory | the last 20 messages of the conversation go to the model; title = the first 60 characters of the first question | Simple; an AI-written title can come later |
| Streaming format | Server-Sent Events on both Harness `POST /api/conversations/{id}/messages` and Gateway `POST /v1/call` with `stream: true`: `event` lines are not used; each `data:` line is one JSON object with `type` (section 6). Headers `Content-Type: text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no` | Contract already says SSE |
| Logs | JSON lines; never request or answer text, keys, tokens or prompts; one line per failover with the entry id only | Global rules |
| Kafka | none in Stage 2 (usage stays in the Gateway's own database; the cost meter and audit writer read events in Stage 3) | Kafka only where it earns its place |

## 5. Data (each service owns its database; two roles each: owner for migrations, app role with no DELETE/TRUNCATE, as in Stage 1)

**Gateway database `modelgateway`** (roles `modelgateway`, `modelgateway_app`; test `modelgateway_test`, `modelgateway_test_app`):
- `usage`: id bigint identity, occurred_at timestamptz, model_entry_id uuid, user_id text, purpose text, tier int null, outcome text (`ok`, `failed`, `skipped_rate`, `skipped_budget`), input_tokens int, output_tokens int, cost_usd numeric(14,6), duration_ms int. **Append-only**: a trigger refuses UPDATE, DELETE and TRUNCATE; the app role has SELECT, INSERT only. Index (model_entry_id, user_id, occurred_at) and (model_entry_id, occurred_at).

**Harness database `harness`** (roles `harness`, `harness_app`; test `harness_test`, `harness_test_app`):
- `conversations`: id uuid, user_id text, title text, created_at, updated_at, deleted_at, created_by, updated_by.
- `messages`: id uuid, conversation_id uuid (FK), role (`user`, `assistant`), content text, tier int null, model_entry_id uuid null, model_title text null, input_tokens int null, output_tokens int null, note text null, outcome (`completed`, `failed`, `tool_requested`), created_at, created_by. Messages are never changed: a trigger refuses UPDATE and DELETE on `messages`; app role SELECT, INSERT.
- A statement trigger refuses DELETE and TRUNCATE on every table (as in the Control Centre).

**Control Centre (`controlcentre`), a new migration** (never edit an applied one): `model_entries` gains `title` text not null default '', `api_key_encrypted` text null, `input_price_per_million` numeric(14,6) not null default 0, `output_price_per_million` numeric(14,6) not null default 0, `timeout_seconds` int not null default 120 (10–900), `request_settings` jsonb not null default '{}'; `secret_ref` becomes optional (empty allowed; ignored by the Gateway; kept for old rows). The audit detail of a model change records `"api_key": "changed"` or `"api_key": "removed"`, never a value.

## 6. Interfaces

### Gateway (`contracts/http/model-gateway.openapi.yaml`, Part A updates it)
- `GET /health` → `{"status":"ok"}` when its database answers.
- `POST /v1/call` (caller must be the Harness service account: `azp` `ooh-harness-api`, aud `ooh-model-gateway`). Body: `purpose`, `tier` (required when purpose is `chat`), `user_id`, `messages` (`role` system/user/assistant, `content`), optional `tools` (`[{name, description, input_schema}]`), `stream`. 
  - `stream: false` → 200 `{content, tool_calls, model_entry_id, model_title, tier, usage: {input_tokens, output_tokens}, cost_usd}`.
  - `stream: true` → SSE `data:` objects: `{"type":"delta","text":...}`, `{"type":"tool_call","id":...,"name":...,"arguments":{...}}`, then one `{"type":"completed","model_entry_id":...,"model_title":...,"tier":...,"usage":{...},"cost_usd":...}` or `{"type":"failed","error":{"code","message"}}`.
  - Errors before streaming: 400 invalid input; 401; 403 wrong caller; 404 `no_model` (no active supported entry for this purpose and tier); 429 `rate_limited` (every entry skipped for rate); 503 `budget_exceeded` (every entry over budget), `unavailable` (every entry failed), `registry_unavailable` (Control Centre did not answer).
- `POST /v1/classify` → 503 `{"code":"not_built_yet","message":"Classification arrives in Stage 3"}` (route kept, contract unchanged except the documented 503).
- Adapters (one module each; nothing above them reads `api_type`):
  - `openai_chat_completions`: `POST {endpoint_url}/chat/completions`, header `Authorization: Bearer <key>`; tools as `{"type":"function","function":{name, description, parameters}}`; streaming with `stream_options: {include_usage: true}`. Examples of `endpoint_url`: `https://api.openai.com/v1`, `https://api.deepseek.com`, an on-prem `http://<host>:8000/v1`.
  - `openai_responses`: `POST {endpoint_url}/responses`, Bearer; `instructions` = the system message; `input` = the other messages; tools `{"type":"function", name, description, parameters}`; `store: false`; streaming events `response.output_text.delta`, `response.completed`. Example: `https://api.openai.com/v1`.
  - `anthropic_messages`: `POST {endpoint_url}/v1/messages`, headers `x-api-key: <key>`, `anthropic-version: 2023-06-01`; `system` = the system message; `max_tokens` from `request_settings.max_tokens`, else 4096; tools `{name, description, input_schema}`; streaming events `content_block_delta`, `message_delta`, `message_stop`. Examples: `https://api.anthropic.com`, `https://api.deepseek.com/anthropic`.
  - `request_settings`: its top-level fields are merged into the provider's request body after the adapter builds it; a value `null` removes that field (the escape hatch when a provider refuses a field).
  - The builder checks every field name above against the provider's official reference on the day and reports any difference; the behaviour does not change.
- Registry: `GET {CC}/api/models?purpose=&tier=` on port 8081 (cached 30 s), key `GET {CC}/api/models/{id}/key` on port 8081 (cached 60 s, no retry rule). Service token cached until 30 s before expiry.

### Harness API (`contracts/http/harness-api.openapi.yaml`, Part B updates it)
- `GET /health`.
- `GET /api/me` → `{user_id, name, chat_tiers: [int], skills: [{name, title}]}` (name from the token's `name` claim; tiers and skills from the Control Centre for this user).
- `POST /api/conversations` → 201 `{id}`; `GET /api/conversations?limit=&before=` → the user's own, newest first `[{id, title, updated_at}]`; `GET /api/conversations/{id}` → `{id, title, messages: [...]}` (own only, else 404).
- `POST /api/conversations/{id}/messages` body `{content, tier?}`: before the stream: the conversation must be the user's (404); tier = the given one or the lowest the user may use (none → 403 `no_tier`, "You have no chat tier yet. An admin can grant one."); `POST {CC}/api/rights/check` for `chat.tier` + tier (not allowed → 403 `tier_not_allowed`; no answer → 503 `rights_unavailable`: fail closed). Then the user message is stored, the Gateway is called with `stream: true`, and the SSE stream to the browser carries `delta`, then `completed` with `{message_id, tier, model_title, usage, note}` or `failed` with `{error}`. The assistant message is stored when the stream ends (partial text with outcome `failed` if it broke).
- `POST /api/uploads`, `GET /api/events`, `GET /api/files/{key}`: answer 503 `{"code":"not_built_yet",...}` in Stage 2 (Stage 3 builds them with the storage contract rewrite).
- Every route needs a user token with aud `ooh-harness-api` (the Workspace's tokens already carry it); `user_id` is always the token's `sub`, never taken from the body.

### Control Centre additions (`contracts/http/control-centre.openapi.yaml`, Part D updates it)
- `ModelInput` gains optional `title`, `api_key` (write-only, 1–4096 characters; an empty string removes the key), `input_price_per_million`, `output_price_per_million`, `timeout_seconds`, `request_settings`; `secret_ref` becomes optional. `ModelEntry` (admin and Gateway views) gains `title`, `has_key`, the two prices, `timeout_seconds`, `request_settings`; **never** the key.
- `GET /api/models/{id}/key` (Gateway only, port 8081 only) → `{api_key}`; 404 when the entry has no key. Not audited per read; logged without the value. `GET /api/models` (Gateway registry) also moves to port 8081 only.
- Existing grant routes are used by the Admin Console for "who may use this tier" (`subject_type` `everyone` or a `user_id`).

## 7. Parallel Parts

Four Codex windows at the same time, each in its own worktree from `stage-2-base`, Full Access (Aziz 13:41). **Rule: no Part changes a file another Part lists.** Nobody changes the files in section 11.

### Part A — Model Gateway (branch `stage-2-part-a`, Codex A, tile 0)
Files (only these):
```
services/model-gateway/**                       (package, migrations, tests, Dockerfile, .dockerignore, README.md, uv.lock)
contracts/http/model-gateway.openapi.yaml
contracts/examples/http/model-gateway.*
contracts/examples/index.model-gateway.json     (index entries for NEW Gateway examples; existing entries stay in index.json, whose example files Part A may update in place)
.github/workflows/model-gateway-image.yml
deploy/apps/model-gateway/*.yaml                 (Deployment with migrate init container, Service, ConfigMap; no Ingress)
deploy/platform/postgres/db-modelgateway.yaml    (2 Databases + 4 DatabaseRoles)
install/64-model-gateway-setup.sh                (database role Secrets, databases, test settings file ~/.config/ooh/model-gateway-test.env, the Gateway's Keycloak client secret copied into Secret model-gateway-oidc; no printing; re-runnable)
install/65-model-gateway-deploy.sh               (<12-character tag>; image check as 61; apply; wait for the new revision and migrations; DONE)
```
Checks: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest` in `services/model-gateway` (database tests included once 64 has run); `uv run --project contracts/check pytest contracts/check/tests`; `bash -n` + `shellcheck` on its scripts; `kubeconform -strict` on its manifests.
Tests must cover: each adapter's request and streamed answer (respx fakes), tools in and tool calls out per adapter, `request_settings` merge and null removal, main → backup before first output, no failover after first output, rate limit skip, budget skip, cost maths, `daily_budget` 0 = no limit, unsupported `api_type` skipped, wrong caller 403, the key never logged (a test captures logs), registry and key caching, append-only `usage` (database test as owner and as app role, rolled back).

### Part B — Harness API (branch `stage-2-part-b`, Codex B, tile 1)
Files (only these):
```
services/harness-api/**                          (package, migrations, bundled skill input schemas, tests, Dockerfile, .dockerignore, README.md, uv.lock)
contracts/http/harness-api.openapi.yaml
contracts/examples/http/harness-api.*
contracts/examples/index.harness-api.json        (index entries for NEW Harness examples; existing entries stay in index.json, whose example files Part B may update in place)
.github/workflows/harness-api-image.yml
deploy/apps/harness-api/*.yaml                   (Deployment with migrate init container, Service named harness-api port 8080 with label app: harness-api, ConfigMap; no Ingress: the existing harness Ingress already sends /api to Service harness-api:8080)
deploy/platform/postgres/db-harness.yaml
install/66-harness-api-setup.sh                  (as 64, for the Harness: Secret harness-api-oidc, test file ~/.config/ooh/harness-api-test.env)
install/67-harness-api-deploy.sh                 (as 65; afterwards deletes the leftover placeholder ConfigMap harness-api, which holds no data)
```
Checks as Part A, in `services/harness-api`. Tests must cover: every route allowed, refused and bad input; fail closed when the Control Centre does not answer or says no; lowest allowed tier chosen; tools only for allowed skills; tool call → the fixed sentence; budget fallback to the lowest allowed tier with its note; SSE order delta… completed; partial answer stored as failed when the Gateway stream breaks; another user's conversation → 404; `user_id` never taken from the body; the bundled schema copies equal the contracts; messages append-only (database test).

### Part C — Workspace app + platform glue + the stage check (branch `stage-2-part-c`, Codex C, tile 4)
Files (only these):
```
apps/workspace/**                                (Angular app, tests, Dockerfile, nginx.conf, .dockerignore, README.md, package-lock.json)
.github/workflows/workspace-image.yml
deploy/apps/workspace/*.yaml                     (Deployment named workspace with label app: workspace, Service workspace:8080, ConfigMap workspace-config with config.json; the existing harness Ingress already sends / to it)
install/68-workspace-deploy.sh                   (image check, apply, wait, delete the leftover placeholder ConfigMap workspace)
install/70-check-stage-2.sh                      (section 9)
install/30-platform-apply.sh                     (stop re-applying the workspace, harness-api and admin-console placeholders once their real Deployment exists, as it already does for control-centre-api; nothing else changes)
install/40-check-platform.sh                     (harness /, admin /: 200 from the real apps (look for the app's root element); harness /api/conversations without a token: 401 once the real harness-api runs, else the placeholder 200; nothing else changes)
deploy/platform/keycloak/realm-ooh.yaml          (ooh-workspace and ooh-admin-console: attribute post.logout.redirect.uris "+" for fresh installs)
install/35-realm-sync.sh                         (also sets post.logout.redirect.uris "+" on those two clients; never creates a client)
docs/ARCHITECTURE.md                             (the Gateway, Harness, both apps as built; keys encrypted in the Control Centre; the storage paragraph is NOT changed in Stage 2)
README.md                                        (Quick Guide, section 10)
```
The Workspace: sign-in page (SignIn screen: Keycloak button, digital rain from the design system, "Sign in with company account" starts the code + PKCE flow; no password fields, Keycloak shows those); chat screen (Main screen): left nav with Chat and the user's conversations (newest first, "New chat"), header with the conversation title and a tier picker showing only the user's tiers ("Tier 1", "Tier 2"…), messages (user right, assistant left, streaming cursor while streaming, mono meta line `tier N · <model title> · <in> in / <out> out tokens` plus the note when present), composer (Enter sends, Shift+Enter new line, Send disabled while streaming), an amber notice for 403 answers with the API's message, a red notice for failures. Jobs, Files and Approvals panels are not shown in Stage 2. The browser reads the SSE stream from `fetch` (POST cannot use EventSource). Tests (`ng test`): the SSE parser (chunks split across lines), the tier picker shows only allowed tiers, a 403 shows its message, the meta line format.
Checks: `npx ng build`, `npx ng test` (no watch), `npm ci` from the lock file; the stage check script with `bash -n` + `shellcheck`; `kubeconform` on its manifests.

### Part D — Control Centre changes + Admin Console app (branch `stage-2-part-d`, Codex D, tile 5)
Files (only these):
```
services/control-centre/**                       (new migration, model fields, key encryption, the two Gateway routes, tests, README)
contracts/http/control-centre.openapi.yaml
contracts/examples/http/control-centre.*
contracts/examples/index.control-centre.json     (new Control Centre examples only; existing entries stay in index.json, whose files Part D may update in place)
apps/admin-console/**
.github/workflows/admin-console-image.yml
deploy/apps/admin-console/*.yaml                 (Deployment named admin-console, label app: admin-console, Service admin-console:8080, ConfigMap admin-console-config; the existing admin Ingress already sends / to it)
deploy/apps/control-centre/deployment.yaml       (CC_KEY_ENCRYPTION_KEY from Secret control-centre-keys key encryption-key; container port 8081 named internal)
deploy/apps/control-centre/service.yaml          (adds port internal 8081; the Ingress keeps 8080)
contracts/identity.md                            (section 15)
install/61-control-centre-deploy.sh              (section 15)
install/62-check-control-centre.sh               (section 15)
install/63-control-centre-keys.sh                (creates Secret control-centre-keys with 32 random bytes, only if missing; never prints; DONE)
install/69-admin-console-deploy.sh               (image check, apply, wait, delete the leftover placeholder ConfigMap admin-console)
```
Control Centre: section 5 and section 6 additions; the app refuses to start without a valid `CC_KEY_ENCRYPTION_KEY` (32 bytes, base64) with a clear log line; a wrong key never leaks in errors. Tests: encryption round trip, tamper detected, key never in any admin response, audit detail or log; the Gateway-only routes refuse admins and the Harness and answer 404 on port 8080; the new fields' validation; old rows without key still listed.
Admin Console: sign-in page (as the Workspace, client `ooh-admin-console`); a signed-in person without realm role `ooh-admin` sees "This console is for administrators." and a sign-out button; Models & tiers screen (AdminModels screen): cards per purpose and tier, the table (purpose · tier, main, backup, where, rate limit, cost-today shown as "—" in Stage 2), "Add model" and "Edit" open the form with the approved fields (name = `title`, purpose, tier for chat only, role, where it runs, connection type with the three options and one help line each with the example endpoints of section 6, endpoint, model ID, API key "Saved · type to replace" — never pre-filled, rate limit per user, daily budget USD with help "0 = no limit", input and output price per million tokens USD, time limit seconds, extra request settings as JSON with validation); "Switch off" removes the entry (asks to confirm); per chat tier a "Who may use this tier" row: "Everyone" toggle (grant/remove an `everyone` grant) and an "Add person by user ID" field (a user grant). No "Test connection" button in Stage 2 (Stage 3). Other nav items are not shown in Stage 2.
Checks: `dotnet format --verify-no-changes`, `dotnet build -warnaserror`, `dotnet test` (database tests included), `dotnet ef migrations has-pending-model-changes`; `npx ng build`, `npx ng test`; contract check; scripts and manifests as the others.

### Merge (after all four Parts pass review)
Codex makes branch `stage-2` from `stage-2-base` in a new worktree `~/projects/worktrees/stage-2`, merges the four branches (the file lists do not overlap), runs every check in section 2 item 7 on a clean worktree, writes `docs/STATUS.md` (the only file written at merge), pushes `stage-2`, and runs each image workflow on demand for the merge commit if the path filter did not start it.

## 8. Fixed names between the Parts

| What | Value |
|---|---|
| Ports | every service and app container listens on 8080 (the Control Centre also on 8081 for the Gateway-only routes, no Ingress); probes: readiness `GET /health` (services) or `GET /` (apps); liveness TCP 8080 |
| Images | `ghcr.io/frozenfussion/ooh-<model-gateway, harness-api, workspace, admin-console>:<first 12 characters of the commit hash>`; init container args `["migrate"]` for the two Python services |
| Gateway environment | `GW_DB_CONNECTION` (Secret `model-gateway-db` key `connection`), `GW_DB_MIGRATE_CONNECTION` (same Secret, key `migrate-connection`, init container only), `GW_OIDC_ISSUER` `https://auth.${DOMAIN}/realms/ooh`, `GW_OIDC_AUDIENCE` `ooh-model-gateway`, `GW_CLIENT_ID` `ooh-model-gateway`, `GW_CLIENT_SECRET` (Secret `model-gateway-oidc` key `client-secret`), `GW_CONTROL_CENTRE_URL` `http://control-centre.${APPS_NAMESPACE}.svc:8081` |
| Harness environment | `HA_DB_CONNECTION`, `HA_DB_MIGRATE_CONNECTION` (Secret `harness-api-db`), `HA_OIDC_ISSUER`, `HA_OIDC_AUDIENCE` `ooh-harness-api`, `HA_CLIENT_ID` `ooh-harness-api`, `HA_CLIENT_SECRET` (Secret `harness-api-oidc` key `client-secret`), `HA_CONTROL_CENTRE_URL`, `HA_GATEWAY_URL` `http://model-gateway.${APPS_NAMESPACE}.svc:8080` |
| Control Centre environment (new) | `CC_KEY_ENCRYPTION_KEY` (Secret `control-centre-keys` key `encryption-key`) |
| Test settings files (accepted exception, test databases only, mode 600) | `~/.config/ooh/model-gateway-test.env` (`GW_TEST_DB_MIGRATE_CONNECTION`, `GW_TEST_DB_CONNECTION`), `~/.config/ooh/harness-api-test.env` (`HA_TEST_DB_MIGRATE_CONNECTION`, `HA_TEST_DB_CONNECTION`) |
| Web app config (`/config.json`) | `{"issuer":"https://auth.<domain>/realms/ooh","clientId":"ooh-workspace" or "ooh-admin-console","apiBase":"/api"}` |
| Manifests | use `${DOMAIN}`, `${PLATFORM_NAMESPACE}`, `${APPS_NAMESPACE}`, `${IMAGE_TAG}` like Stage 1; scripts render them from `deploy/values/do.env` |
| Client secrets into Kubernetes | read inside the Keycloak pod with `kcadm.sh get clients/<id>/client-secret` (logged in as in `35-realm-sync.sh`), captured on harness, written with `kubectl create -f -` from standard input; never printed, never an argument, never a trailing newline (`jq -j`) |

## 9. `install/70-check-stage-2.sh` (Part C), one `PASS`/`FAIL` line each, then `DONE`

Every token comes from client secrets read inside the Keycloak pod as `62` does. Two port-forwards, started and stopped by the script (section 15): 18080 → Service `model-gateway` 8080, 18081 → Service `control-centre` 8081.
1. `https://harness.<domain>/` and `https://admin.<domain>/` answer 200 with each app's root element; each app's `/config.json` holds its client id.
2. `https://harness.<domain>/api/conversations` without a token → 401; with the Control Centre's own service token (wrong audience) → 401.
3. No Ingress in any namespace has a backend Service `model-gateway`.
4. Gateway through 18080: the Control Centre's service token on `/v1/call` → 401 or 403; the Harness service token with purpose `chat` and tier 98 (no entries) → 404 `no_model`.
5. Tiers: as the Gateway's service account through 18081, `GET /api/models?purpose=chat&tier=N` for N = 1..20. For every active entry with `has_key` true: one non-streamed `/v1/call` pinned with `model_entry_id`, message `Reply with the single word OK.`, a new `user_id` `stage-check-<uuid>` per call → 200, non-empty content, that entry's title, usage > 0; an entry skipped for budget prints `FAIL <title>: over its daily budget today`. Then one streamed pinned call per connection type in use → at least two `delta` events, then `completed`.
6. The Gateway's `usage` table has one new row per call above: counted from a short-lived check pod as `modelgateway_app`, password from its Secret through the environment (as `40` does), never on a command line.
7. No key in the logs: each key is read once through 18081 (`GET /api/models/{id}/key`, Gateway token) into a variable; the Control Centre, Gateway and Harness logs since the check began are read and compared inside bash (`[[ $logs == *"$key"* ]]`); never printed, never an argument.
8. `GET /api/models/{id}/key` as the Harness service account through 18081 → 403; the same route on the public host `https://admin.<domain>/api/models/<id>/key` with the Gateway's token → 404 (the route is not public).
The device sign-in is not needed: every call above uses service accounts; the browser tests of Done-when 3 and 5 cover real people. Each run makes one short paid call per entry with a key (README says so).

## 10. README Quick Guide additions (Part C writes them; each with where to type, which password, good result)
1. The Stage 2 order on a fresh server: 63 → 61 → 64 → 65 → 66 → 67 → 68 → 69 → 35 → (admin adds models in the browser) → 70.
2. Each script's command, folder (`~/projects/worktrees/stage-2` until accepted, then the main clone) and good result.
3. Adding a model in the Admin Console, with one example per connection type: OpenAI (`openai_responses`, `https://api.openai.com/v1`), Anthropic (`anthropic_messages`, `https://api.anthropic.com`), DeepSeek (`openai_chat_completions`, `https://api.deepseek.com`, or `anthropic_messages`, `https://api.deepseek.com/anthropic`), on-prem (`openai_chat_completions`, `http://<host>:8000/v1`), with placeholder model IDs (never a real model name in the repo).
4. Giving people a tier ("Who may use this tier").
5. Everyday: logs, restart, which image runs, for each of the four new deployments; what to do after a reboot.
6. Builder checks for the two Python services and the two apps.
7. Every new `STOP:` and `FAIL` message and what to do.

## 11. Files that already exist (spec author's; Codex does not change them)
`AGENTS.md`, `CLAUDE.md`, `LICENSE`, `docs/specs/*`, `docs/plan/*`, `docs/images/*`, `docs/design/*`, `apps/design-system/*`, `contracts/check/*`, `install/01-server-setup.sh`, and every earlier file not listed in a Part. If a Part believes one must change, it stops and asks with the reason.

## 12. Pre-mortem

| Step | Failure | How it shows | Action |
|---|---|---|---|
| Streaming | Traefik or nginx buffers SSE | answer appears all at once | `X-Accel-Buffering: no`, `Cache-Control: no-store`; Claude tests a stream through `https://harness.<domain>/api` before Aziz does |
| Provider fields | a field name differs from what the adapter sends | provider 400 | builder checks references on the day; Claude tests each provider with Aziz's key through the Gateway before the browser test; `request_settings` can remove a refused field |
| Keys | wrong or missing encryption key | Control Centre will not start | run 63 before deploying the new Control Centre image |
| Placeholders | 30 re-applied over a real app | real app replaced by the placeholder page | Part C's change to 30; check with 40 |
| Sign-in | redirect or logout refused by Keycloak | Keycloak error page | 35 must run (post-logout redirect URIs); redirect URIs already on both hosts |
| Gateway to Control Centre | 401 from the Control Centre | Gateway log "registry unauthorized" | the Gateway's token must carry aud `ooh-control-centre` (realm already maps it); 64 copied the right client secret |
| Budget | Stage 1 check entry `stage-check` with budget 0 | — | 0 = no limit, and its `api_type` is unsupported, so the Gateway skips it anyway |
| Memory | six new pods on 16 GB | Pending pods | requests small (Python 100m/128Mi, apps 10m/32Mi); report actual use |

## 13. Out of scope for Stage 2
Skill jobs on Kafka and the Slides worker, uploads, files and job events, the storage contract rewrite, classifier routing and `/v1/classify`, health checks on a timer, the Overview, Approvals, People & rights, Audit, Skills and Failed messages screens, branded sign-in, ordinary users' name and email in the Control Centre, an AI-written conversation title, Helm, tracing, AWS. Codex does not pre-build any of it.

## 14. Changes agreed during the build — these override the sections above

**Rows 13 onwards override sections 15, 16 and 17 wherever they differ** (in particular section 15 "History sent to the model: no system message" and "Security of chat text: plain text … no Markdown library").

| # | Change | Who / when |
|---|---|---|
| 1 | Spec review by Claude Code before the builders started (38 findings, `reviews/stage-2-spec-review` in the course folder): every finding is resolved in section 15, which is binding and overrides any line above that disagrees | Spec author, 10 Nov 14:00 |
| 2 | Spec re-review (37 of 38 fixed, 8 new small findings, `reviews/stage-2-spec-rereview`): the earlier sections edited in place to agree with section 15; section 15 gains "Re-review additions" | Spec author, 10 Nov 14:04 |
| 3 | Final check (`reviews/stage-2-spec-final`): section 9 rewritten to match section 15; port 8081 in the Ports row; 62 keeps one check user; tiers with grants but no model stay visible | Spec author, 10 Nov 14:06 |
| 4 | The Gateway's registry answer (`GET /api/models`, Part D) includes `created_at` (UTC), so the Gateway can order entries by creation time | Spec author, 10 Nov 14:13 (asked by Codex A) |
| 5 | Conversation paging: `GET /api/conversations?before=<conversation id>` — the id of the last conversation shown; ordered by `updated_at` then `id`, newest first; `limit` default 20, maximum 100. Parts B and C both use it | Spec author, 10 Nov 14:13 (B) and 14:21 (C) |
| 6 | Part D removes the obsolete duplicate-model 409 entry from `contracts/examples/index.json` and its example file (the one edit Part D makes to `index.json`) | Spec author, 10 Nov 14:13 (asked by Codex D) |
| 7 | `GET /api/admin/models` gains an optional `after=<model entry id>` cursor (limit and maximum unchanged); with no `after` the answer is exactly as in Stage 1. The Admin Console reads every page, so any number of models can be shown | Spec author, 10 Nov 14:21 (asked by Codex D) |
| 8 | The contract check runs with the explicit path: `uv run --project contracts/check pytest contracts/check/tests` (the bare command also collects the service tests and fails). Done-when 7 and the Part checks are edited in place | Spec author, 10 Nov 14:33 (review of A and B) |
| 9 | Gateway, mixed skips: if no entry was called and at least one was skipped for rate, the answer is 429 `rate_limited`; 503 `budget_exceeded` only when every entry was skipped for budget | Spec author, 10 Nov 14:33 (review of A) |
| 10 | Harness API checks only `aud` `ooh-harness-api` (the extra `azp` check is removed). The Harness image workflow keeps its read-only runtime check before publishing (agreed deviation) | Spec author, 10 Nov 14:33 (review of B) |
| 11 | Every builder that uses `dotnet` ends its checks with `dotnet build-server shutdown`, so no .NET build daemon outlives a check (global rule: nothing left running in the background) | Spec author, 10 Nov 14:36 (review of D) |
| 12 | Test connection button moved from Stage 3 into Stage 2 (section 16): Admin Console → Control Centre → Gateway pinned call; Gateway also accepts the Control Centre's service token for pinned, non-streamed calls only, and returns the provider's status and short message on failure | Aziz, 10 Nov 15:38 |
| 13 | Request access (section 17): newcomers register themselves with name, email, organisation, reason and their own password; the Workspace shows "waiting for approval" until an admin approves them with a tier on the new Access requests screen; only approved people get grants, Everyone included | Aziz, 10 Nov 16:21–16:26 |
| 14 | `70` streamed calls send "Count from 1 to 20, separated by spaces." (a one-word reply can arrive as one delta, so "Reply with the single word OK." cannot prove streaming); a FAIL line adds safe counts only: delta count, last event type, HTTP status | Spec author, 10 Nov 16:33 (found on the live run) |
| 15 | **Model names in the Workspace (Aziz, 16:38).** The composer's field is labelled "Chat model" and each option reads "<model title> - Tier <n>" (the title of that tier's active main entry with the lowest priority, then created_at; just "Tier <n>" when the tier has no active main entry). Control Centre `/api/rights/me` adds `chat_tier_titles` `{"<tier>": "<title>"}` (Part D); Harness `/api/me` passes it through as `chat_tier_titles` (Part B); Workspace shows it (Part C); contracts and examples updated by each | Aziz, 10 Nov 16:38 |
| 16 | **Reply language (Aziz, 16:38: DeepSeek answered "hi" in Chinese).** The Harness puts one system message first in every Gateway call, from setting `HA_SYSTEM_PROMPT` in ConfigMap `harness-api-config` (data, changeable without a new image), default: "You are the assistant in Open Office Harness. Always reply in the same language as the user's latest message." Empty setting = no system message. Never logged. Part B (code, ConfigMap, test) | Aziz, 10 Nov 16:38 |
| 17 | **Chat polish (Aziz, 16:39).** Workspace only (Part C): (a) every message, the user's and the assistant's, shows its date and time (local time of the browser, e.g. "10 Nov 2026, 16:39"; from the message's `created_at`, or the send / completion time for the message being streamed); (b) every message has a **Copy** button that copies the message's original text (the markdown source) and shows "Copied" for 2 s; (c) assistant messages render **Markdown** (headings, lists, tables, links opening in a new tab, inline code, and code blocks with their own Copy button) and **LaTeX maths** (`$...$`, `$$...$$`, `\(...\)`, `\[...\]`) while streaming and after; user messages stay plain text. Libraries: `marked`, `dompurify` and `katex` (the builder pins exact current versions checked on the day and reports them). All rendered HTML goes through DOMPurify; raw HTML in model output is never rendered; KaTeX runs with `throwOnError: false` and `trust: false`. Tests: timestamps, copy, a table, a code block, inline and display maths, and a `<script>` and an `onerror=` in model output are not executed | Aziz, 10 Nov 16:39 |
| 18 | **AI-written conversation title (Aziz, 16:41)** — overrides section 13's "an AI-written conversation title" out of scope. After the **first** assistant answer in a conversation completes, the Harness makes one extra non-streamed Gateway call on the user's **lowest allowed tier** (same rights check, same `user_id`, so it counts against that tier's rate and budget): system "Write a short title (3 to 6 words) for this conversation. Reply with the title only, no quotes, no full stop.", then the user's first message and the first answer (each cut to 2000 characters). The answer is trimmed, quotes and a final full stop removed, cut to 60 characters, and stored as the conversation title (`updated_at` unchanged by this). If the call fails, the title stays as today (the first words of the first message) and one log line `title_failed` with the Gateway code is written, never the text. The SSE stream gains one last event `{"type":"title","conversation_id":...,"title":...}` after `completed` when a title was made, so the Workspace updates the list at once (Part C shows it). Part B: code, contract, tests (success, failure keeps the old title, only on the first answer, lowest tier used). Part C: handle the `title` event | Aziz, 10 Nov 16:41 |
| 19 | **Thinking switch (Aziz, 16:43: "get these things done now instead of stage 3").** Admin Console model form gains "Settings when thinking is off (JSON object)", stored by the Control Centre as `request_settings_thinking_off` (jsonb, nullable; null = this model has no switch; same object rule and same CHECK as `request_settings`; new forward migration) and returned in the registry and admin answers (Part D). Control Centre `/api/rights/me` adds `chat_tier_thinking_switch` `{"<tier>": true|false}` from the same main entry as row 15 (Part D). Harness `/api/me` passes it through; `POST .../messages` takes optional `thinking` (boolean, default true) and sends it to the Gateway (Part B). Gateway `/v1/call` takes optional `thinking` (default true); when false and the entry has `request_settings_thinking_off`, that object is merged over the request body after `request_settings` (same null-removes rule); when the entry has none, `thinking` is ignored (Part A). Workspace shows a "Thinking" on/off switch next to the Chat model picker only when the chosen tier's switch is true; the choice is remembered per tier in the browser (Part C). Examples for Aziz's models (README, Part C): DeepSeek `{"thinking":{"type":"disabled"}}`; OpenAI `{"reasoning":{"effort":"low"}}`; Claude Opus 5.5 none (thinking cannot be switched off). Tests per Part; contracts and examples updated | Aziz, 10 Nov 16:43 |
| 20 | **Asking for another model (Aziz, 16:43).** In the Workspace the Chat model picker ends with "Request another model…". It opens a small panel listing the tiers the person does not have yet that have an active main entry ("<title> - Tier <n>"), an optional reason (at most 300 characters) and **Send request**; a tier already requested shows "Requested" instead. Control Centre (Part D): table `tier_requests` (id, user_id, tier, reason, status `pending|approved|rejected`, requested_at, decided_at, decided_by, standard columns, `deleted_at`, no-DELETE trigger, audited like `access_requests`, audit detail without the reason); `/api/rights/me` adds `requestable_tiers` `[{tier, title, requested}]`; `POST /api/tier-requests` (Harness service account only, body `{user_id, tier, reason}`, only for approved people and tiers in `requestable_tiers`, one pending request per user and tier, at most 20 pending per user); the Access requests screen gains a second list **Model requests** (name and email from `access_requests`, tier with model title, reason, requested at) with Approve (adds the user grant for that tier) and Reject, and its count joins the nav badge. Harness (Part B): `POST /api/tier-requests` for the signed-in user → Control Centre, and passes `requestable_tiers` in `/api/me`. Workspace (Part C): the picker option and panel. Tests per Part; contracts and examples updated | Aziz, 10 Nov 16:43 |
| 21 | **Select boxes (Aziz, 16:43: the drop-down arrow touches the right border).** Every select in the Workspace (Part C) and the Admin Console (Part D) leaves room for its arrow: the design-system select with right padding of at least `space-6` and the arrow inset by `space-3`. If the fix belongs in `apps/design-system/bundle.css`, the builder says so in its report instead of changing that file (spec-author file) | Aziz, 10 Nov 16:43 |
| 22 | **Review decisions for rows 15–21** (`reviews/stage-2-rows-15-21-review`; binding, override rows 15–21 where they differ). (1) Row 16: the system message overrides section 15; the title call (row 18) uses only its own system message, never `HA_SYSTEM_PROMPT`; changing `HA_SYSTEM_PROMPT` = edit `deploy/apps/harness-api/configmap.yaml`, then 67 (README says a live edit is overwritten by the next deploy). (2) Row 17 overrides section 15's plain-text rule. DOMPurify with `FORBID_TAGS: ['img','svg','math','style','iframe','form','input','video','audio','object','embed']` for model output (KaTeX HTML is produced by our code after sanitising the Markdown, and inserted as its own sanitised fragment with KaTeX's tags allowed); links only `http:`, `https:`, `mailto:`; an `afterSanitizeAttributes` hook adds `target="_blank" rel="noopener noreferrer"`. KaTeX CSS and fonts are bundled in the app (no CDN); the KaTeX licence goes next to the other licences. While streaming, the whole message is re-rendered at most 10 times a second; unfinished maths stays as text until it closes. Tests add: an outside image is not rendered; a `javascript:` link is dropped. (3) Row 18: the title call uses **the tier that answered the first message** (not the lowest tier: no text goes to a provider the user did not choose), `user_id` `title-<sub>` (not counted against the user's rate limit; budget and cost still count), a fixed 20 s limit; only when the first assistant message with outcome `completed` is stored and the conversation still has its default title. The Workspace treats `completed` as the end of the answer (composer enabled again) and applies a later `title` event if one arrives on the same stream, which the Harness closes after the title call or its 20 s. (4) Row 19: README gives shapes by connection type with placeholder model names only: `openai_chat_completions` services that support it `{"thinking":{"type":"disabled"}}` or `{"reasoning_effort":"low"}`; `openai_responses` `{"reasoning":{"effort":"low"}}`; `anthropic_messages`: leave empty when the model has no off switch. No real model names in the repo. The Gateway's `completed` event and non-streamed answer add `thinking_applied` (true/false) and the Workspace meta line shows "thinking off not supported by this model" when the user switched thinking off and it was not applied (backup or failover). The Control Centre test call rule (16.1 item 2) still refuses any extra field, `thinking` included. **Part A** builds row 19's Gateway part (files: `services/model-gateway/**`, its contract, examples, `index.model-gateway.json`) and merges `origin/stage-2-access-requests` first. (5) Row 20: `requestable_tiers` never lists tier 99 nor a tier the person already gets through any grant (user or Everyone); `requested` is `"pending" | "rejected" | null`; a rejected tier can be requested again after 7 days. `POST /api/tier-requests` answers 201 `{id,status}`, 403 `not_approved`, 400 `tier_not_requestable`, 409 `already_requested`, 429 `too_many_requests` (20 pending per user). Admin routes: `GET /api/admin/tier-requests?status=&limit=&after=`, `GET /api/admin/tier-requests/count?status=pending`, `POST /api/admin/tier-requests/{id}/approve` and `/reject`, 409 when already decided, 409 `not_approved` when the person's access is no longer approved; they hide `stage-check-` users; name and email fall back to the user ID when there are no `access_requests` details. All user text in the console is plain text; the reason is never logged or audited. (6) Row 21: the spec author fixes `apps/design-system/bundle.css` on the spec branch (`.ooh-select` right padding and arrow position); the Parts change nothing for row 21 except removing any local override that fights it. (7) Rows 15 and 19: the picker's name and switch come from the tier's main entry; the meta line (real answering model) is the truth when a backup answers. (8) Contracts per Part: Part D Control Centre `/api/rights/me` (`chat_tier_titles`, `chat_tier_thinking_switch`, `requestable_tiers`), model field `request_settings_thinking_off`, tier-request routes; Part B Harness `/api/me` (those three plus `access`), `POST .../messages` `thinking`, SSE `title` event, `POST /api/tier-requests`; Part A Gateway `thinking`, `thinking_applied`; Part C none. Examples in each `index.<area>.json` | Spec author, 10 Nov 16:48 |
| 23 | **Answers during the final build** (spec author): `thinking_applied` = whether the requested thinking choice was honoured (on → true; off with off-settings merged → true; off with none → false), in the Gateway answers and the Harness SSE `completed` event only (not stored); titles only after a `completed` answer; a repeat model request within 7 days of a rejection answers **409 `too_soon`** "You can ask for this model again 7 days after the last answer" (Control Centre), passed through by the Harness, shown by the Workspace; a rejected tier shows "Not approved" with Send request | Spec author, 10 Nov 16:50–17:16 |
| 24 | **Visible thinking (Aziz, 19:01: "It should have an expandable thinking that the user should be able to see").** Providers (checked on their docs 10 Nov): `openai_chat_completions` services may return `reasoning_content` (full message) / `delta.reasoning_content` (stream); `anthropic_messages` returns `thinking` blocks and `content_block_delta` with `delta.type` `thinking_delta` (`delta.thinking`) only when the request has `thinking.display` `summarized` (set per model in its extra request settings — data, not code); `openai_responses` returns no reasoning text. **Part A (Gateway):** each adapter turns those into SSE events `{"type":"thinking","text":...}` (before or between `delta` events, never after `completed`), and the non-streamed answer adds `thinking` (string or null); empty strings are dropped; signatures, encrypted reasoning and redacted blocks are never forwarded; thinking text is never logged and counts in usage as the provider reports it. The builder confirms the streamed DeepSeek field name against the provider's docs on the day. **Part B (Harness):** passes `thinking` events through the stream; stores the concatenated thinking text with the assistant message in a new nullable column `thinking` (forward migration; app role unchanged: SELECT, INSERT), returns it in conversation history, never logs it, and never sends stored thinking back to any model. **Part C (Workspace):** each assistant message with thinking shows a collapsed **Thinking** section above the answer ("Thinking" with a chevron; click to open or close); while streaming it shows "Thinking…" and fills live; plain text only (no Markdown, no HTML); the message's Copy button copies the answer only, and the Thinking section has its own Copy. Contracts and examples by each Part. Out of scope: passing reasoning back for tool use (Stage 3) | Aziz, 10 Nov 19:01 |
| 25 | **Request access on the Workspace sign-in screen (found 18:46).** The Workspace sign-in card adds a second button **Request access** under "Sign in with company account" that opens Keycloak's registration page for `ooh-workspace` directly (the OIDC client's authorize request with `prompt=create`, which Keycloak 26 maps to registration; the builder confirms this on 26.8.2). Part C | Spec author, 10 Nov 19:03 |
| 26 | **Greeting uses the browser's local time (found 17:59: "Good morning" at 18:00 Malaysia time).** Morning before 12:00, afternoon 12:00–17:59, evening from 18:00, from the browser's clock. Part C | Spec author, 10 Nov 19:03 |
| 27 | **Review decisions for rows 24–26** (`reviews/stage-2-rows-24-26-review`; binding, override rows 24–26 where they differ). (1) The title call sends `thinking: false` and ignores any `thinking` in the answer; a title is never made from thinking. (2) `openai_responses` **is included**: when the entry's extra request settings ask for it (`reasoning: {"summary": "auto"}`), Part A maps `response.reasoning_summary_text.delta` to `thinking` events and `reasoning` output items' `summary[].text` to the non-streamed `thinking`; `encrypted_content` is never forwarded. (3) `openai_chat_completions`: read `reasoning_content`, else `reasoning` when it is a string, in both `message` and `delta`; ignore `reasoning_details` and object forms; test both names. (4) A `thinking` event counts as output: after it, no failover; a failure after thinking but before answer text ends as `failed` and the thinking so far is kept. (5) The Harness stores at most the first 100 000 characters of thinking per message (later thinking still streams, not stored); history returns `thinking` on every message. (6) Thinking is stored for every outcome, `failed` included, and shown on failed messages; history sent to any model selects `role` and `content` only, never `thinking`; Part B tests that stored thinking never reaches a later Gateway call or the title call. (7) Thinking text is never written to a log, an exception message, the Gateway call table, the audit trail or any Kafka event; it is stored only in `messages.thinking`; Parts A and B extend their log-capture tests with a thinking event. (8) Anthropic: thinking text appears when the entry's extra settings switch thinking on and set `display: summarized`; a thinking block with no text is dropped; README says manual `budget_tokens` needs a `max_tokens` above it in the same settings. (9) Each side ignores stream event types it does not know; deploy Gateway, then Harness, then Workspace; each contract lists `thinking` in its stream event `oneOf`. (10) When the answer text is empty, the Workspace shows the Thinking section and the outcome line only. (11) Request access button: `this.auth.authorize(undefined, { customParams: { prompt: 'create' } })`; if Keycloak 26.8.2 shows the sign-in page instead, use `/realms/ooh/protocol/openid-connect/registrations` with the same request; a unit test checks `prompt: 'create'`; 70 checks with curl that the authorize URL with `prompt=create` returns the registration form (`kc-register-form`). (12) The Admin Console sign-in screen gets no Request access button. (13) The greeting is worked out when the sign-in screen is shown (no live update); tests use a fixed clock at 11:59, 12:00, 17:59 and 18:00. (14) Docs: Part A Gateway README (settings that turn thinking on, per connection type, placeholder names), contract, examples; Part B migration (next number after the latest on `stage-2` at 2e05fa8), Harness README, contract, examples; Part C Workspace README and the 70 lines; Part D nothing | Spec author, 10 Nov 19:08 |
| 28 | **Organisation is optional (Aziz, 18:34: the admin was stopped at sign-in by Keycloak's "Update Account Information" page).** A required user-profile attribute applies to every existing account, so `organisation` has no `required` block; it still shows on the registration form. 35 removes an existing `required` block on a live realm (7542212). Overrides section 17 and 17.8 item 3 | Aziz, 10 Nov 18:34 |

## 15. Decisions from the spec review (binding; override anything above that disagrees)

**Who deploys.** Claude runs the non-sudo deploy and check scripts in tile 3 where Aziz watches (Aziz, 10 Nov 13:41, "all for your new plan"); Aziz keeps sudo, the reboot, sign-ins, passwords, the GitHub package switches and "accepted". The global rules section 1 now says so.

**Any number of models per tier** (Aziz, 13:32: "as many as I want in whichever tier"). Part D adds a migration that drops the unique index `models_active` on (purpose, tier, role) and adds `priority` int not null default 100 (1–1000) to `model_entries`. `role` stays (main / backup) as a label. The Gateway tries the active entries of a purpose and tier in this order: role `main` before `backup`, then `priority` ascending, then `created_at`. The Admin Console shows and edits `priority` ("Order within the tier, lowest first").

**Stage 1 check keeps passing.** `install/62-check-control-centre.sh` moves to Part D: its check model entry uses tier **99** (not 2) and its rights checks use `chat.tier` target `"99"`, so real tiers and "Everyone" grants never collide with it. Spec files belong to the spec author: Part D notes the change in its report and the spec author adds a row to Stage 1 section 14 at merge.

**Gateway-only routes are not public.** The Control Centre listens on a second port **8081** that has no Ingress (Service `control-centre` gains port `internal` 8081). `GET /api/models/{id}/key` and `GET /api/models` (Gateway registry) are served **only** on 8081 and answer 404 on 8080. The Gateway uses `http://control-centre.<apps namespace>.svc:8081`. Part D: Program, deployment.yaml, service.yaml, tests (each Gateway-only route 404 on 8080). `deploy/apps/control-centre/service.yaml` joins Part D's list. 62's Gateway registry check runs through a short-lived `kubectl port-forward` to 8081.

**Keys follow their address.** Changing `endpoint_url` or `api_type` on an entry with a saved key removes the key unless a new key is typed in the same save; the Admin Console says so next to the key field. AES-GCM uses the model entry id as associated data (a key copied to another row cannot be decrypted). Audit detail: `"api_key": "set"`, `"changed"` or `"removed"`; never a value; a test proves the audit `View` never contains the key or the encrypted text.

**Lost encryption key.** If the Secret `control-centre-keys` is lost, the saved provider keys are re-typed in the Admin Console (provider keys can always be re-issued). `63` refuses to overwrite an existing Secret; the README says this plainly and how to copy the Secret to a private place if Aziz wants a backup.

**User IDs for grants.** The Workspace shows "Your user ID" (from `/api/me`) on a small "About me" line under the user's name, with a copy button, so a user can send it to an admin. People's names and emails in the Control Centre stay in Stage 3 (STATUS is corrected at merge).

**Asking for a tier you do not have** returns 403 `tier_not_allowed` "You don't have tier N. An admin can grant it." (the Workspace only offers allowed tiers, so this happens only for crafted requests). The classifier's fallback-with-a-note in ARCHITECTURE.md is Stage 3 routing; Part C rewrites that paragraph to say so.

**Anthropic.** Keep `anthropic-version: 2023-06-01` with `x-api-key` (both accepted by Anthropic and DeepSeek today); the builder confirms on the day. The README warns that `temperature`, `top_p` and `top_k` added through extra request settings may be refused by newer Anthropic versions.

**Files with no owner, now owned:**
- `contracts/identity.md` → Part D (Gateway service-account row: registry and key routes on port 8081; keys encrypted in the Control Centre; device sign-in on `ooh-admin-console` stays until Stage 3).
- `install/61-control-centre-deploy.sh` → Part D (also checks Secret `control-centre-keys`: `STOP: run install/63-control-centre-keys.sh`; also applies the Service change).
- `install/62-check-control-centre.sh` → Part D (tier 99; registry check through port 8081).
- Root README: each Part writes its STOP/FAIL rows and its everyday commands in its own `services/*/README.md` or `apps/*/README.md`; Part C's root Quick Guide links to them and lists the stage order. The merge step may also copy those rows into the root README (merge writes STATUS.md and that README section only).
- Leftover placeholder ConfigMap `control-centre-api` → deleted by `69` (Part D).
- `35-realm-sync.sh` may run any time after the merge; it runs before the browser tests.

**Names fixed.** ConfigMaps: `model-gateway-config`, `harness-api-config`, `workspace-config`, `admin-console-config`. Deployment selectors are exactly `matchLabels: {app: <deployment name>}`, nothing else (the placeholders use the same selector, so the apply replaces them). Every real Deployment also carries the pod label `ooh/app: real`; `30` and `40` tell real from placeholder by that label (Deployment exists and its template has `ooh/app: real`).

**GitHub packages.** The four new packages start private. After the first green run of each workflow Claude opens each package's settings page in a new tab of Aziz's browser and Aziz clicks Change visibility → Public (same as Stage 1). This step is in the stage order before `65`.

**Grants per tier.** Part D adds `GET /api/admin/grants?right_key=&limit=&after=` (admin) → active grants of that right, ordered by id. The Admin Console uses it for the "Who may use this tier" row.

**Gateway order** is decided by the Gateway as above, never by the registry's answer order.

**Harness answers when the Gateway says no** (all JSON before any stream byte, `{code, message}`):
| Gateway | Harness to browser |
|---|---|
| 404 `no_model` | 503 `no_model` "No model is set up for tier N yet. An admin can add one." |
| 429 `rate_limited` | 429 `rate_limited` "You are sending messages too fast for tier N. Wait a minute." |
| 503 `budget_exceeded` | the budget fallback to the lowest allowed tier with its note; when there is no lower tier: 503 `budget_exceeded` "Tier N has used its daily budget. Try again tomorrow or ask an admin." |
| 503 `unavailable` | 503 `unavailable` "The model did not answer. Try again." |
| 503 `registry_unavailable` or no answer | 503 `unavailable` (same text) |
A failure after the stream started is a `failed` event with the same codes and texts.

**Rights check body** is exactly `{"user_id":"<sub>","action":"chat.tier","target":"<tier as a string>"}`.

**History sent to the model.** No system message in Stage 2. The last 20 messages of the conversation with outcome `completed` (user messages always count) and non-empty content, oldest first, starting at a user message; then the new user message.

**Tool call in a stream.** The fixed sentence goes out as one `delta` (after any text already streamed), then `completed`; the stored assistant content is the streamed text plus the sentence, outcome `tool_requested`.

**Rate limit counts** usage rows with outcome `ok` or `failed` only; calls still streaming have no row yet (accepted).

**Gateway pin for checks.** `/v1/call` takes an optional `model_entry_id`: when given, only that entry is tried (no failover). Used by `70` (and by Stage 3's Test connection). Only the Harness service account may call `/v1/call` at all.

**`70-check-stage-2.sh` changes:**
- Tiers to test: as the Gateway's service account through the port-forward to the Control Centre's port 8081, `GET /api/models?purpose=chat&tier=N` for N = 1..20; every active entry found with `has_key` true is called pinned by `model_entry_id`; a streamed call per connection type in use.
- `user_id` for the check calls: `stage-check-<uuid>`.
- The README says each run of 70 makes one short paid call per entry with a key.
- Item 3 becomes: no Ingress in any namespace has a backend Service `model-gateway`.
- Item 6: usage rows counted from a short-lived check pod as the `modelgateway_app` role, password from its Secret through the environment (as 40 does), never on a command line.
- Item 7: no admin view (the Control Centre tests cover it); the key search covers the Control Centre, Gateway and Harness logs since the check began; each key is read through the 8081 route into a variable and compared inside bash (`[[ $logs == *"$key"* ]]`), never printed, never an argument.
- Every token comes from client secrets read inside the Keycloak pod as 62 does.

**Security of chat text.** Assistant and user text is shown as plain text with line breaks (`white-space: pre-wrap`); no HTML, no Markdown library, no `innerHTML`.

**Python images.** `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1`; `uv` comes from `ghcr.io/astral-sh/uv:0.13.7` pinned by digest in the build stage only; the run stage has no uv; read-only root works (report how it was checked).

**Connection types: exact handling** (from the providers' pages on 10 Nov 2026; builders re-check on the day):
- `openai_chat_completions`: take the last non-null `usage` seen in any chunk (`prompt_tokens`, `completion_tokens`); join `delta.tool_calls[]` pieces per `index` (`id`, `function.name`, `function.arguments` string pieces); send no `max_tokens`/`max_completion_tokens` unless `request_settings` sets one.
- `openai_responses`: text from `response.output_text.delta` (`delta`); tool calls from `response.output_item.added` (type `function_call`, `call_id`, `name`) plus `response.function_call_arguments.delta`/`.done`; finish on `response.completed`; `response.failed`, `response.incomplete` and `error` are failures (or, after output began, a `failed` event); usage `response.usage.input_tokens` / `output_tokens`; tools sent with `strict: false`; length limit `max_output_tokens` only when `request_settings` sets it.
- `anthropic_messages`: input tokens from `message_start` (`message.usage.input_tokens`); output tokens = the last `message_delta` usage value (a running total, never summed); tool calls from `content_block_start` (type `tool_use`, `id`, `name`) plus `input_json_delta.partial_json` pieces; `error` event = failure; `ping` and unknown events ignored.
- The reason we need OpenAI Responses: OpenAI's newest models need it for tool calls; chat completions stays for every other OpenAI-compatible service. Neither type is forced on all OpenAI models: the admin picks per entry.

**Kept simple.** The key cache is 60 s, with no retry rule. Health reporting from the Gateway moves to Stage 3 with Test connection: no health route, no health state in Stage 2 (the `health` field keeps its value). The budget fallback stays (Aziz's approved form). `request_settings` must be a JSON object (the Admin Console and the Control Centre both refuse anything else).

**Re-review additions.**
- `70` uses a new `stage-check-<uuid>` for each Gateway `/v1/call`, so the check never hits its own rate limit (`62` keeps one `stage-check-<uuid>` for its whole run, as today: it makes no Gateway calls); an entry skipped for its budget prints `FAIL <entry title>: over its daily budget today`.
- A pinned `model_entry_id` must be one of the active entries of the given purpose and tier, else 404 `no_model`; rate limit and budget still apply to a pinned call.
- A user message is stored with outcome `completed`. The history window is read **before** the new user message is stored, then the new message is appended once.
- With the unique index gone, Part D removes the duplicate-entry 409 for model entries from the contract, its example and its test, and drops the matching unique `HasIndex` in the EF model (`has-pending-model-changes` must say no changes).
- The Admin Console shows a tier row for every tier that has an active chat model entry **or** an active grant, except tier 99 (the Stage 1 check's tier); a tier with grants but no model shows "No model yet", so grants are never hidden.
- GitHub packages: Claude opens each package's settings page (`https://github.com/users/frozenfussion/packages/container/<name>/settings`) in a new tab of Aziz's built-in browser on his PC; Aziz clicks Change visibility → Public.
- Every `kubectl port-forward` in `62` and `70` is started by the script on a fixed local port (`62`: 18081; `70`: 18080 for the Gateway, 18081 for the Control Centre), stopped by a trap on exit, and a busy port is `STOP: local port <n> is busy; stop the old port-forward (pkill -f "port-forward.*<n>") and re-run`.

## 16. Test connection button (added during the build; binding)

**Aziz's words (10 Nov 15:38):** "Since you are fixing it, why not also put a test button? That's pretty important, I think." This moves Stage 3's Test connection into Stage 2. Section 13 no longer lists it.

**What the admin sees.** Each model row in Models & tiers gets a **Test** button in Actions (only when the entry has a saved key; otherwise the button is disabled with the hint "Save a key first"). Pressing it sends one short paid call to that entry only, and shows the result under the row until the next test or reload:
- success: `Works · <seconds, one decimal> s · reply: "<first 80 characters>" · <input>/<output> tokens · $<cost, 6 decimals>`;
- failure: `Failed · <reason in plain words> (provider answered <HTTP status>)` plus the provider's own short message when there is one. Reasons: `key refused` (401/403), `model or endpoint not found` (404), `rate limited by the provider` (429), `took longer than its time limit`, `could not reach the endpoint`, `unexpected answer`, `over its daily budget today`, `no key saved`.
While a test runs the button shows "Testing…" and is disabled. No key is ever shown or sent to the browser.

**Flow.** Admin Console → Control Centre (public port 8080, admin only) → Gateway `/v1/call` pinned with `model_entry_id` → the provider. The Control Centre calls the Gateway with its own service token. Nothing else may call the Gateway as the Control Centre.

**Control Centre (Part D).**
- `POST /api/admin/models/{id}/test` (role `ooh-admin`, port 8080): 404 if the entry does not exist; 409 `no_key` if it has no key. Otherwise one non-streamed Gateway call: `purpose` and `tier` of the entry, `model_entry_id`, `user_id` `admin-test-<admin's sub>`, messages `[{"role":"user","content":"Reply with the single word OK."}]`, `stream: false`. Answer 200 `{ok: true, model_title, reply, duration_ms, usage: {input_tokens, output_tokens}, cost_usd}` or 200 `{ok: false, reason, provider_status, provider_message}` (the Gateway's error mapped to the reasons above; `provider_status` and `provider_message` null when there is none).
- One audit row `model.tested` per test: entry id, ok, reason, duration_ms. Never the reply text, the key or the provider message.
- Service token: client credentials for `ooh-control-centre` from `https://auth.<domain>/realms/ooh`, secret from env `CC_CLIENT_SECRET` (Secret `control-centre-oidc`, key `client-secret`), cached until 30 s before expiry. Gateway address from env `CC_GATEWAY_URL` = `http://model-gateway.${APPS_NAMESPACE}.svc:8080` (ConfigMap `control-centre`). HTTP time limit = the entry's `timeout_seconds` + 10 s.
- `install/71-control-centre-oidc.sh` (new, Part D): reads the `ooh-control-centre` client secret inside the Keycloak pod as `64` does and creates Secret `control-centre-oidc` once (never overwrites; prints `DONE`). `61` stops with "run install/71-control-centre-oidc.sh" when the Secret is missing.
- Files added to Part D: `install/71-control-centre-oidc.sh`, `deploy/apps/control-centre/configmap.yaml`. Contract: the route in `contracts/http/control-centre.openapi.yaml` with examples.
- Tests: success and each failure mapping (fake Gateway), 409 without key, 404, non-admin 403, the audit row has no reply/key/provider message, the token is cached.

**Admin Console (Part D).** The Test button and result line as above; tests for both results, the disabled state without a key and the "Testing…" state.

**Gateway (Part A).**
- `/v1/call` also accepts the Control Centre service account (`azp` `ooh-control-centre`), **only** when `model_entry_id` is given and `stream` is false; anything else from that caller → 403 `forbidden`. The Harness rules are unchanged.
- When a pinned call fails, the error body adds `provider_status` (the provider's HTTP status, or null) and `provider_message` (the provider's error message text, at most 300 characters, null when none). Before returning it, the Gateway removes the entry's key from the text if it appears and replaces it with `[removed]`. The `code` stays as section 6 says; a timeout gives code `unavailable` with `provider_status` null and `provider_message` "time limit reached"; an unreachable endpoint gives "could not connect".
- Usage rows are written as for any call (the test costs money and counts against the entry's daily budget).
- Tests: the Control Centre caller pinned and non-streamed → allowed; unpinned or streamed → 403; `provider_status` and `provider_message` for 401, 404, 429 and 500 answers per adapter; the key is removed from a provider message that echoes it; timeouts.

**Realm (Part C).** `ooh-control-centre` gets the audience mapper `audience-ooh-model-gateway` (access token only), in `deploy/platform/keycloak/realm-ooh.yaml`; `install/35-realm-sync.sh` already syncs audience mappers for every client and must add this one on an existing realm. `install/70-check-stage-2.sh` step 4 changes: the Control Centre's service token on `/v1/call` **unpinned** → 403, and pinned + streamed → 403.

**Order to deploy.** 35 → 71 → 65 (new Gateway image) → 61 (new Control Centre image) → 69 (new console image) → 70.

### 16.1 Review decisions for section 16 (Claude Code review `reviews/stage-2-test-button-spec-review`; binding, override section 16 where they differ)

1. **Result mapping goes by the Gateway's `code` first**, `provider_status` only when the Gateway passed the provider's answer through:

   | Gateway answer | Reason shown |
   |---|---|
   | 401 / 403 from the Gateway itself | the Control Centre could not sign in to the Gateway (also one setup-error log line in the Control Centre) |
   | `no_model` | entry is not active or its connection type is not supported |
   | `rate_limited` | over this entry's rate limit; wait a minute |
   | `budget_exceeded` | over its daily budget today |
   | `registry_unavailable` | the Control Centre registry did not answer |
   | `unavailable` + `provider_status` 401 or 403 | key refused |
   | `unavailable` + 402 | the provider account has no credit |
   | `unavailable` + 404 | model or endpoint not found |
   | `unavailable` + 429 | rate limited by the provider |
   | `unavailable`, no status, "time limit reached" | took longer than its time limit |
   | `unavailable`, no status, "could not connect" | could not reach the endpoint |
   | anything else | unexpected answer |
2. **The Control Centre caller can send only the test call:** `model_entry_id` given, `stream` false, `messages` exactly `[{"role":"user","content":"Reply with the single word OK."}]`, no `tools`, `user_id` starting `admin-test-`. Anything else → 403 `forbidden`; one test per refusal.
3. `caller()` stays authentication only. One rule after body validation decides: Harness → as today; Control Centre → only the call in item 2; anyone else → 403. `/v1/classify` stays 403 for the Control Centre.
4. **`provider_message`:** at most 300 characters. Remove the full key, any run of 8 or more characters that appears in the key, and anything matching `sk-[A-Za-z0-9_-]+` or `sk-ant-[A-Za-z0-9_-]+`, each replaced with `[removed]`. The Admin Console shows it as plain text only (no HTML binding). Neither the Gateway nor the Control Centre ever logs `provider_message` or the reply.
5. **Reading the provider's error:** on a non-2xx answer the adapter reads at most 4 KiB of the body and takes `error.message` (OpenAI and Anthropic shape), else the text. Attached only to pinned calls; the Harness path never receives these fields. **Also, for every failed provider attempt (pinned or not), the Gateway logs one JSON line `{"message":"provider_failed","model_entry_id":...,"provider_status":<int or null>,"reason":"http|timeout|connect|bad_answer"}`, never the body.** (Found live: the first DeepSeek test failed and the logs showed only "failover".)
6. **Contracts:** Part A adds a `PinnedError` schema (`code`, `message`, `provider_status` int or null, `provider_message` string or null) for 503 answers of pinned calls, with examples in `index.model-gateway.json`. Part D adds the test route's 200 shapes (`ok` true / false), 403, 404 and 409 to the Control Centre contract, with examples in `index.control-centre.json`.
7. **Overrides Stage 0 section 13 row 6** ("The Control Centre client gets no Model Gateway audience"). Part D updates `contracts/identity.md`: the Control Centre service account may call Gateway `/v1/call` only for the pinned test call. Part C updates `docs/ARCHITECTURE.md`: the Control Centre "calls AI only through the Gateway's pinned test call".
8. **Files per Part (in addition to section 7):**
   - Part A: `services/model-gateway/**`, `contracts/http/model-gateway.openapi.yaml`, its examples, `index.model-gateway.json`.
   - Part C: `deploy/platform/keycloak/realm-ooh.yaml`, `install/35-realm-sync.sh`, `install/70-check-stage-2.sh`, `README.md` (order gains 71: 63 → 71 → 61 → …), `docs/ARCHITECTURE.md`.
   - Part D: `services/control-centre/**`, `apps/admin-console/**`, `contracts/http/control-centre.openapi.yaml`, its examples, `index.control-centre.json`, `contracts/identity.md`, `deploy/apps/control-centre/configmap.yaml` and `deployment.yaml`, `install/61-control-centre-deploy.sh`, `install/71-control-centre-oidc.sh`.
9. **Where the work happens:** each Part keeps its branch and worktree (`stage-2-part-a`, `-c`, `-d`), first merges `origin/stage-2-test-button` into it (that is `stage-2` plus this section), builds, runs its section 7 checks, pushes, and reports. Claude Code reviews each Part; then Claude merges the three branches into `stage-2` and reruns the section 2 item 7 checks before deploying.
10. **`control-centre-oidc`:** 71 behaves like 64: create if missing; if present and different from Keycloak's current secret, `STOP: the Control Centre client secret changed; …`. `CC_CLIENT_SECRET` is **optional** in the Deployment (`optional: true`): without it the Control Centre starts normally and the test route answers `{ok:false, reason:"the Control Centre has no service credentials"}`. 61 does not stop for it.
11. Token URL = `CC_OIDC_ISSUER` + `/protocol/openid-connect/token`; client ID fixed `ooh-control-centre`; the secret goes only in the form body, never in a URL or log line.
12. **Audit:** `action` `model.tested`, `target` = the entry's `model_id` (as other model rows), detail `{model_entry_id, ok, reason, duration_ms}`; one row for success and for failure, plus the usual `audit.events` message.
13. **Time limits:** the Admin Console stops waiting at `timeout_seconds` + 15 s and shows "took longer than its time limit". When the Control Centre's own limit fires it answers 200 `{ok:false, reason:"took longer than its time limit", provider_status:null, provider_message:null}`.
14. **70 positive check:** the Control Centre's service token, pinned to an entry with a key, the fixed test message, `stream` false → 200 with non-empty content (one paid call, skipped with a note when no keyed entry exists). Plus the refusals: unpinned → 403, streamed → 403, other messages → 403.

## 17. Request access (added during the build; binding)

**Aziz's words (10 Nov 16:21–16:26):** "they'll try to log in, or if they don't have a username password, they're going to request access, where they're going to enter their name, email address ... And then in the admin, I'm going to get a request to approve." Agreed at 16:26 ("go"): they choose their own password when they request access; Aziz only presses Approve (with a tier) or Reject; no mail server.

This overrides section 13 for "ordinary users' name and email in the Control Centre": the Control Centre now stores name, email, organisation and reason for people who request access.

**What a newcomer sees.** The sign-in page (harness and admin) shows "Need access? **Request access**". The form asks: first name, last name, work email (also the username), organisation or team (optional, row 28), why you need access (optional, at most 300 characters), password and confirm password. After sending it they are signed in to the Workspace, which shows only: "Thanks, <first name>. Your request is waiting for approval." and Sign out. A rejected person sees "Your request was not approved. Please contact your administrator." and Sign out. An approved person sees the normal Workspace.

**What the admin sees.** A new nav item **Access requests** in the Admin Console with the number waiting (hidden when 0). The screen lists requests with filters Waiting / Approved / Rejected (Waiting first, newest first): name, email, organisation, reason, requested at. Each waiting row has a tier list (the chat tiers that exist) and **Approve**, and **Reject**. A rejected row has **Approve** (with a tier). Approving or rejecting shows the new state at once.

**Who may use the Workspace (the rule, enforced in the Control Centre, fail closed).** A person is *approved* when their access row says `approved`. Only approved people get any grant, including **Everyone**. Rows become approved by: Approve on this screen; an admin adding them by user ID on a tier (adding a person approves them); being an admin (a person with realm role `ooh-admin` seen by the Control Centre is approved automatically); or the migration backfill (every user already in `people` or in an active user grant when the migration runs is approved, so nobody loses access).

### 17.1 Keycloak realm (Part C)
- `deploy/platform/keycloak/realm-ooh.yaml`: `registrationAllowed: true`, `registrationEmailAsUsername: true`, `loginWithEmailAllowed: true`, `duplicateEmailsAllowed: false`, `verifyEmail: false`, `resetPasswordAllowed: false` (no mail server); `bruteForceProtected` stays true.
- User profile: two extra attributes shown on registration, editable by the user only at registration: `organisation` (optional, 0–100 characters; row 28) and `access_reason` (optional, 0–300 characters), with display names "Organisation or team" and "Why do you need access?". The builder checks the exact realm-import shape for the declarative user profile against the Keycloak version in use (`deploy/platform/keycloak`) and reports it.
- Realm texts (localization, English): `noAccount` = "Need access?", `doRegister` = "Request access", `registerTitle` = "Request access".
- `ooh-workspace` client: user-attribute mappers `organisation` and `access_reason` into the **access token** only (the standard `name`, `email`, `given_name` claims come from the default scopes).
- `install/35-realm-sync.sh` applies all of the above to an existing realm (realm settings, user profile, texts, mappers) and stays re-runnable.

### 17.2 Harness API (Part B)
- `GET /api/me` first calls the Control Centre `POST /api/access/observe` (Harness service token) with `{user_id: sub, name, email, organisation, access_reason}` taken from the user's token (missing claims → null; strings trimmed and cut to the limits above), then the rights call as today. It adds `access`: `approved` | `pending` | `rejected` to its answer. When the observe call fails, `/api/me` answers 503 `rights_unavailable` (fail closed), as the rights call does.
- No other Harness route changes: rights checks already fail closed, and the Control Centre now returns no grants for people who are not approved.
- Contract: `access` in the `/api/me` answer, with examples. Tests: claims passed through, limits applied, observe failure → 503, `access` returned.

### 17.3 Control Centre (Part D)
- New table `access_requests`: `id` uuid, `user_id` text unique, `name`, `email`, `organisation`, `reason` (text, nullable), `status` (`pending`, `approved`, `rejected`, CHECK), `requested_at`, `decided_at` (nullable), `decided_by` (nullable), `approved_tier` int nullable, plus the standard `created_at/updated_at/created_by/updated_by`. A business table: every insert and status change writes an audit row (`access.requested`, `access.approved`, `access.rejected`) and the usual `audit.events` message, with no password (there is none) and no token.
- Migration backfill: an `approved` row (decided_by `migration`) for every `people.user_id` and every user subject of an active user grant at migration time. Forward migration only.
- `POST /api/access/observe` (caller must be the Harness service account, `azp` `ooh-harness-api`; anyone else 403): creates a `pending` row if none exists (audited); while `pending`, updates name/email/organisation/reason if they changed (audited); never changes an `approved` or `rejected` row's status. Answers `{status}`.
- `People.Observe`: a person whose token has realm role `ooh-admin` gets an `approved` row if they have none or theirs is not approved (audited, decided_by `system:admin-role`).
- Grants: `POST /api/admin/grants` for a `user` subject also sets that user's row to `approved` (creating it if missing; audited) in the same transaction.
- Rights: `Decision`, `/api/rights/me` and `/api/skills` give **nothing** to a user whose row is missing or not `approved` (Everyone included). One test per path.
- Admin routes (role `ooh-admin`): `GET /api/admin/access-requests?status=&limit=&after=` (default `pending`, newest first, limit default 50, max 200, `after=<id>`); `GET /api/admin/access-requests/count?status=pending` → `{count}`; `POST /api/admin/access-requests/{id}/approve` `{tier}` → the tier's right must exist (else 400); sets `approved`, `approved_tier`, `decided_at`, `decided_by`, and creates the user grant for `chat.tier.<tier>` if not already there, all in one transaction; `POST /api/admin/access-requests/{id}/reject` → `rejected`. Approve on an approved row → 409; reject on a rejected row → 409.
- Contract: all routes with examples in `index.control-centre.json`; `contracts/identity.md` gains the Harness → Control Centre observe call.
- Tests: observe create/update/no status change; non-Harness caller 403; backfill; admin auto-approve; grant-approves; rights give nothing to pending, rejected and unknown users (including Everyone); approve creates the grant; 409s; audit rows on each change.

### 17.4 Admin Console (Part D)
The Access requests screen and nav count as above, using the design system (same table, buttons, select and spacing as Models & tiers). Names, emails, organisation and reason are shown as plain text only. Tests: list per filter, approve with a tier, reject, count badge hidden at 0.

### 17.5 Workspace (Part C)
`/api/me.access` decides: `pending` and `rejected` show only the messages above with Sign out (no conversation list, no composer, no other API calls); `approved` shows the Workspace as today. Tests for all three.

### 17.6 Stage check (Part C, `install/70-check-stage-2.sh`)
- Keycloak's registration page for `ooh-workspace` answers 200 and shows "Request access" and the two extra fields.
- As the Harness service account through the Control Centre: `POST /api/access/observe` for a new `stage-check-<uuid>` user → `pending`; `GET /api/rights/me` for that user → no tiers and no skills even when a tier has Everyone.
- No person is created in Keycloak by 70.

### 17.7 Files per Part
- Part B: `services/harness-api/**`, `contracts/http/harness-api.openapi.yaml`, its examples, `index.harness-api.json`.
- Part C: `deploy/platform/keycloak/realm-ooh.yaml`, `install/35-realm-sync.sh`, `install/70-check-stage-2.sh`, `apps/workspace/**`, `README.md` (Quick Guide: how a newcomer requests access and how the admin approves), `docs/ARCHITECTURE.md`.
- Part D: `services/control-centre/**`, `apps/admin-console/**`, `contracts/http/control-centre.openapi.yaml`, its examples, `index.control-centre.json`, `contracts/identity.md`.
- Each Part merges `origin/stage-2-access-requests` into its own branch first; Claude Code reviews each Part; Claude merges into `stage-2`.

**Order to deploy.** 35 → 61 → 67 → 68 → 69 → 70.

**Out of scope here:** email verification and password-reset emails (need a mail server), notifying the admin outside the console, deleting requests.

### 17.8 Review decisions for section 17 (Claude Code review `reviews/stage-2-access-spec-review`; binding, override section 17 where they differ)

Defaults chosen by the spec author where the review asked Aziz; Aziz may change any of them.
1. **Existing users who only had Everyone** request access once and Aziz approves them (in practice only test accounts). No special migration path. README says so.
2. **Deploy order:** 61 → 67 → 35 → 68 → 69 → 62 → 70 (the rule and observe exist before registration opens). Backfill takes only `people` rows with `first_seen_at` before the migration time and user grants created before it.
3. **User profile:** `organisation` and `access_reason` are user-editable (Keycloak 26 has no "registration only"; harmless, because the Control Centre copies them only while a request is pending). `organisation`: no `required` (row 28), validator `length` max 100; `access_reason`: validator `length` max 300; both `permissions {view:[admin,user], edit:[admin,user]}`. 35 **reads** the current profile (`GET /admin/realms/ooh/users/profile`), adds or updates only these two attributes, keeps every other attribute and `unmanagedAttributePolicy`, writes it back, and reads it again to verify. Fresh install: the realm's `components` entry `org.keycloak.userprofile.UserProfileProvider` with `kc.user.profile.config` holding the full JSON (defaults plus the two attributes).
4. **Exact mechanics for 35:** `kcadm update realms/ooh -s registrationAllowed=true -s registrationEmailAsUsername=true -s loginWithEmailAllowed=true -s duplicateEmailsAllowed=false -s editUsernameAllowed=false -s verifyEmail=false -s resetPasswordAllowed=false -s internationalizationEnabled=true -s 'supportedLocales=["en"]' -s defaultLocale=en -s 'passwordPolicy=""'`; texts via `PUT /admin/realms/ooh/localization/en/<key>` (`text/plain`) for `noAccount`, `doRegister`, `registerTitle`; mappers `oidc-usermodel-attribute-mapper` (`user.attribute`, `claim.name`, `access.token.claim: true`, `id.token.claim: false`, `userinfo.token.claim: false`), synced by name and never removed by the audience clean-up. The same settings are in `realm-ooh.yaml` (`localizationTexts`, `components`, client `protocolMappers`). With `editUsernameAllowed: false` and email as username, a user cannot change their email; the builder confirms this on Keycloak 26.8.2 and reports it.
5. **"Request access" is Keycloak's own link** on its login page (the realm texts). The apps' sign-in screens keep their single button. The Admin Console's non-admin page adds: "To request access, open the Workspace: https://harness.<domain>" as a link (only the Workspace creates requests).
6. **Admins:** the Harness also sends `is_admin` (from the verified user token's `realm_access.roles` containing `ooh-admin`) in `observe`; the Control Centre approves such a person (`decided_by system:admin-role`, audited). `People.Observe` keeps doing the same.
7. **Check users:** 70 uses one fixed user ID `stage-check-access` (observe is idempotent) and expects any status other than `approved`. The Access requests list and count **hide user IDs starting `stage-check-`**.
8. **The Everyone check moves to 62 (Part D):** 62 grants Everyone on tier 99, checks that a pending `stage-check-` user gets no tier 99 and an approved one does, then removes that grant. 70 keeps only the observe → not approved check and the registration-page check.
9. **Revoke:** approved rows show **Revoke** (status `rejected`, audited `access.revoked`); a revoked person gets nothing, Everyone included. Rejected rows show **Approve**. 
10. **Adding a person by user ID approves them**, including a rejected one (audited `access.approved`, `decided_by` the admin). The Control Centre does not look up Keycloak. The tier panel shows a short note under "Add person": "Adding a person also approves their access."
11. **Spam:** at most **100 waiting** requests; past that, `observe` creates nothing and answers `{status:"closed"}`, and the Workspace says "Requests are closed for now. Please contact your administrator." The Access requests screen labels every email "not verified". No CAPTCHA now (README says how to switch registration off with 35 if spam appears: a `--registration off` flag on 35).
12. No password-strength policy (Stage 4 phase 2 section 17 row 14 supersedes the original policy).
13. Self-registered users can sign in to the Admin Console and see the non-admin page; accepted.
14. **Audit:** access audit rows hold `user_id`, `status`, `decided_by`, `approved_tier` only, never name, email, organisation or reason; `audit.events` carries the usual fields only.
15. Part D changes `contracts/identity.md` "Self-registration is off" to "Self-registration is on; a newcomer waits for approval"; the device sign-in rule stays.
16. `access_requests` gets `deleted_at` (unused in Stage 2) and the same no-DELETE/TRUNCATE trigger as the other business tables; the app role has no DELETE.
17. **Details:**
    - the Approve tier list uses the same tiers as Models & tiers (an active entry or grant, never tier 99), with none preselected; Approve stays disabled until a tier is chosen;
    - approving when the user already has that tier's grant adds no second grant;
    - the count route takes `status=pending` only;
    - `observe` matches the exact `sub`;
    - field limits after trimming: name 200, email 320, organisation 100, reason 300;
    - when `/api/me` answers 503, the Workspace shows its normal red notice, not the waiting screen.
18. **Forgotten passwords:** the README (Part C) adds "Reset someone's password" (Keycloak admin console → Users → the person → Credentials → Reset password, temporary on). The Account Console stays reachable.

**Files added by 17.8:** Part B: none new. Part C: `install/35-realm-sync.sh` gains `--registration off|on`. Part D: `install/62-check-control-centre.sh`.
