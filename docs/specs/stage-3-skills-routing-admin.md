# Stage 3 — Skills on Kafka, read-only consumers, classifier routing, admin screens

Written 2026-11-11 by Claude (orchestrator). Read `00-GLOBAL-RULES.md` first; it applies in full.
**Base commit:** `main` right after this spec is merged. Before any Part starts, Codex tags that commit `stage-3-base` and pushes the tag (`git tag -a stage-3-base -m "Stage 3 base" && git push origin stage-3-base`). Phase 1 Parts start from that tag.
**Tags:** `pre-routing` on the merged and checked phase 1 (section 7, "Phase 1 merge"); `spine-v0.3` when Aziz accepts the stage.

## 0. Aziz's words and decisions (Malaysia time)

- 07 Nov 16:26–16:30 (planning chat): rights are fixed rules in the Control Centre, never decided by an AI. The classifier is a Model Gateway purpose (`classification`), swappable (Jev, OpenAI's options), used for (a) routing in the Harness (tier and skill suggestions) and (b) the safety watcher on Kafka, which classifies prompts and outputs and raises flags to the approvals inbox. "Classifier answers are suggestions. Thresholds are settings. Every score is logged to `audit.events`." Tier routing: `needs_tier2` → rights check `chat.tier 2` → allowed: tier 2; not allowed: tier 1 + a note.
- 07 Nov (planning chat, technology table): the Slides worker is Python with python-pptx; workers call the Gateway, write to storage and publish `skill.results`.
- 08 Nov: build everything end to end in the rehearsal, including classifier routing; tag `pre-routing` before routing is merged so it can be rebuilt live in class (D043). The Admin Console opens on an Overview: greeting, needs-attention list (sign-ups, tier requests, approvals, safety flags, outages, dead letters) and system health (D035).
- 09 Nov 16:56: the realm shows as "OOH" — ugly; wants a branded sign-in page; no forced password change for an admin who typed his own password (D070, moved into Stage 3 by the faster plan).
- 10 Nov 13:32: nothing about AI providers is hard-coded; models, tiers, connection types and keys are data added in the Admin Console.
- 10 Nov 13:41: the faster plan (D082): Stage 3 = skills on Kafka + read-only consumers + classifier routing (tag `pre-routing` before the routing Part is merged) + the remaining Admin Console screens; four builders in parallel; Codex with Full Access.
- 10 Nov 22:04: "a skill is a right like a tier": a person requests it once in the Workspace and an admin approves it once in the Admin Console, like Request another model (D091). The per-job approval switch (`needs_approval` in the manifest) is false for Slides and exists for risky skills and safety flags.
- 11 Nov 18:47–18:51: "go ahead and start"; the PowerPoint skill is built by us from scratch; full permissions for the builders; "do not cut corners in writing the specs"; log everything.

## 1. Purpose

A person asks the Workspace chat "make me slides about X". The chat model calls the Slides skill as a tool; the Harness checks the right, publishes the job to Kafka and the chat answers at once ("I've started your presentation"). Our own Slides worker asks the AI for the slide text, builds a real PowerPoint file, stores it and publishes the result. The job card in the Workspace turns from "Queued" to "Ready" with a Download button. The chat never waits for the worker; if the worker is down, the job waits in Kafka and finishes when it returns.

Three read-only helpers listen on Kafka: the **audit writer** keeps one append-only trail of everything across services, the **cost meter** keeps the cost of every model call, and the **safety watcher** asks the classifier about each chat message and each skill result and raises a flag in the Approvals inbox when a score is high. Messages that fail three times go to a dead-letter topic and appear in the Admin Console.

The admin gets the remaining Admin Console screens (Overview, Approvals, People & rights, Audit), approves skill requests like model requests, and sees model and service health. The sign-in page is branded "Open Office Harness", and device sign-in on the admin client is switched off.

Phase 2 adds **classifier routing**: with "Auto" chosen in the model picker, the classifier suggests whether a question needs tier 2 and whether it wants a skill; the fixed rights still decide; the meta line says what happened.

## 2. Done when (all of these)

1. GitHub Actions builds every changed image on push (and on demand): the five existing ones plus `ghcr.io/frozenfussion/ooh-slides-worker`, `ooh-audit-writer`, `ooh-cost-meter`, `ooh-safety-watcher`, each tagged with the first 12 characters of the commit hash; all pull without logging in.
2. On harness, from the merged `stage-3` worktree, every script in the README order (section 10) ends with `DONE` (Claude runs them in tile 3 where Aziz watches; none needs sudo). All pods in `ooh-apps` are Ready.
3. `install/77-check-stage-3.sh` prints `PASS` for every line and ends with `DONE` (section 9); `40`, `62` and `70` still pass.
4. In the browser (Aziz): (a) the sign-in page says "Open Office Harness" in the design-system look; (b) in the Workspace he asks for a presentation; the chat answers at once, a job card shows Queued then Ready, Download saves a `.pptx` that opens in PowerPoint with a title slide and content slides; (c) with a second account without the Slides right, the Slides skill is not offered, "Request a skill" sends a request, Aziz approves it in Approvals, and the second account can then make slides; (d) the Overview shows today's people, skill jobs, model calls and cost, the needs-attention list and system health; (e) People & rights shows people × tiers and skills and a change takes effect; (f) Audit shows one request end to end by its request ID (rights check, job published, model call, result, safety check, cost).
5. Phase 2 (after `pre-routing`): with "Auto", a simple question goes to tier 1, a hard question goes to tier 2 when the person has tier 2 and stays on tier 1 with a note when they do not; "make slides about X" with the Slides right starts the Slides job; the meta line shows the routing; the scores are in the Audit screen.
6. After `sudo reboot`, `40`, `62`, `70` and `77` pass again without anyone touching the server (allow 5 minutes), and the browser flows work.
7. In a clean worktree of `stage-3`: every Part's checks pass; `uv run --project contracts/check pytest contracts/check/tests` passes; `bash -n` and `shellcheck` are clean for every `install/*.sh`; `kubeconform -strict` passes on `deploy/`.
8. `README.md` Quick Guide covers section 10; `docs/STATUS.md` says Stage 3 is done and lists what was checked; `docs/ARCHITECTURE.md` and `contracts/storage.md` describe what was built.

## 3. Prerequisites (before the builders start)

1. Tiles: 0 CODEX A, 1 CODEX B, 2 CLAUDE CODE, 3 SHELL Aziz (sudo), 4 CODEX C, 5 CODEX D (rebuilt 11 Nov 18:50).
2. The contract changes in section 6.1 are part of this spec's pull request (spec author's files); every Part starts from them.
3. Test databases: Part A's `66` (Harness, unchanged roles) already exists; Part B writes `74` first (audit writer and cost meter test databases); Claude runs it as soon as it is pushed (no sudo). Until then Part B runs only the tests that need no database and says so.
4. No Kafka in unit tests: every Part fakes the Kafka client behind its own small interface. Real Kafka is exercised only by the stage check and the browser tests.

## 4. Decisions for this stage (fixed; versions checked 11 Nov 2026 on pypi.org)

| Item | Decision | Why |
|---|---|---|
| Python services | as Stage 2: Python 3.14.10, `python:3.14.10-slim-trixie`, non-root `10001`, uv 0.13.7, FastAPI 0.162.2, uvicorn 0.54.0, pydantic 2.14.3, httpx 0.28.1, psycopg[binary] 3.3.8, PyJWT[crypto] 2.15.1, pytest 9.2.0, respx 0.23.1, ruff 0.17.4 | Same proven stack |
| Kafka client (Python) | **confluent-kafka 2.16.1** (wheel for Python 3.14 with librdkafka built in; SCRAM-SHA-512) | Same library family as the Control Centre's Confluent.Kafka 2.16.0; no system packages |
| PowerPoint | **python-pptx 1.0.2** (brings lxml 6.1.3, Pillow 13.0.0, XlsxWriter 3.3.1, typing-extensions 4.16.0, all pinned in the lock file) | Planning chat 07 Nov; the standard library for writing .pptx |
| JSON Schema in Python | **jsonschema 4.26.0** (Harness tool input, worker input, consumers' envelope and payload checks) | Same version as the contract checker |
| .NET and Angular | unchanged from Stage 2 (Confluent.Kafka 2.16.0, JsonSchema.Net 9.6.0, Angular 22.2.5, angular-auth-oidc-client 22.0.2) | No new framework |
| Kafka connection | `ooh-kafka-kafka-bootstrap.${PLATFORM_NAMESPACE}.svc:9092`, SASL_PLAINTEXT, SCRAM-SHA-512, one principal per service, consumer group = principal name, `enable.auto.commit` false (commit after handling), `auto.offset.reset` earliest | Strimzi listener from Stage 0; contract `identity.md` |
| Consumer rules (every consumer) | skip an `event_id` already handled; a message that fails the envelope or payload schema goes straight to `dlq.<topic>` (no retries); any other failure is retried 3 times (waits 1 s, 5 s, 15 s), then a `dlq.entry` to `dlq.<topic>` and move on | Global rules; same numbers as the Control Centre |
| Idempotency without extra tables | a service that publishes because of an incoming message makes the outgoing `event_id` = UUID v5 of the incoming `event_id` (namespace `6f1d5b7e-3c1a-4b8e-9a52-1f0c8f3e2d10` + the outgoing type), so a repeated input gives the same output id and the receiver drops it | No processed-events table in the worker or the safety watcher |
| Files | the existing volume `ooh-files` (20Gi, `ooh-apps`, local-path, Retain) mounted at `/files`: read-write in the Slides worker, read-only in the Harness. Key layout `outputs/<skill>/<correlation_id>/<file>`; the worker writes to a temporary name in the same folder and renames when complete | Stage 0 row 2: files on the Droplet disk, no Spaces. On EKS (Stage 6) a different volume type, same paths |
| Downloads | the Workspace calls `GET /api/files/{key}` with its bearer token; the Harness checks the key belongs to a completed job of this user and streams the file (`Content-Disposition: attachment`); the browser saves the blob. No signed links | No extra secret, no exception to "every route needs a token" |
| Chat with tools | the Harness runs the tool loop: model → tool call → Harness acts → tool result back to the model → the model's next answer, at most 2 tool rounds per user message (a third tool call is answered "Tool limit reached for this message." and the stream ends). The model's reasoning for that turn is passed back to it exactly as the provider requires (section 6.3) | Carried from Stage 2; DeepSeek with thinking needs it; real agentic loop for the course |
| Skill title | from the manifest's `title` | Already in the manifest |
| Classification connection types | a `classification` entry may use `jev_systemone` (POST `{endpoint}/v1/systemone`, section 6.3) or one of the three chat types (the model is asked for a JSON object of scores). `jev_systemone` is offered only for purpose `classification` | Aziz uses Jev today (HOORA AI `classify.ts`); D020 swappable |
| Thresholds and questions | settings in ConfigMaps (Harness routing, safety watcher), never in code; a change = edit the ConfigMap file + redeploy (README) | Planning chat: "thresholds are settings" |
| Who acts as admin in checks | a confidential Keycloak client `ooh-stage-check` with a service account holding realm role `ooh-admin`; **disabled** except while a check runs (the check enables it at start and disables it on exit, also on failure); its secret is read inside the Keycloak pod at check time and never stored | Replaces device sign-in, which this stage switches off (identity contract); no standing admin credential |
| Health | the Gateway reports a model entry's health to the Control Centre when it changes; the Control Centre asks every service's `/health`, Kafka and Keycloak every 30 s | D086 moved health to Stage 3; Overview "System health" |
| Dead letters | the Control Centre reads every `dlq.*` topic into a table and shows them (view and count). Replay is Stage 4 (failure demos) | Identity contract defers replay; COURSE-MAP Day 2 demo |
| Uploads | not built (`POST /api/uploads` stays 503) | Slides input is text only; not in D082 |
| Logs | as before; never message text, prompts, file contents, keys or tokens; the safety watcher logs only ids and scores | Global rules |

## 5. Data (each service owns its database; owner role for migrations, app role without DELETE/TRUNCATE; business tables with the standard columns and `deleted_at`; append-only tables with a trigger refusing UPDATE, DELETE, TRUNCATE)

**Harness (`harness`), new migration `0003_jobs.sql`:**
- `jobs`: id uuid (= the job's `correlation_id`), user_id, conversation_id uuid null, message_id uuid null, skill text, skill_version text, input jsonb, status (`awaiting_approval`, `queued`, `completed`, `failed`, `rejected`), output jsonb null, error jsonb null, standard columns. Index (user_id, created_at desc, id).
- `processed_events`: event_id uuid primary key, topic, handled_at (system table, insert only).

**Audit writer (`auditwriter`; roles `auditwriter`, `auditwriter_app`; test `auditwriter_test`, `auditwriter_test_app`):**
- `trail` (append-only): id bigint identity, event_id uuid unique, occurred_at, received_at, producer, correlation_id uuid, user_id, actor, action, target, outcome, model text null, tokens int null, cost_usd numeric(14,6) null, scores jsonb null. Indexes (correlation_id), (occurred_at desc, id desc), (user_id, occurred_at desc).

**Cost meter (`costmeter`; roles `costmeter`, `costmeter_app`; test `costmeter_test`, `costmeter_test_app`):**
- `model_costs` (append-only): id bigint identity, event_id uuid unique, occurred_at, user_id, action (`model.call`, `model.classify`), model text, model_entry_id text, tokens int, cost_usd numeric(14,6). Index (occurred_at).

**Control Centre (`controlcentre`), new migrations (never edit an applied one):**
- `skill_requests`: as `tier_requests` (Stage 2 row 20) with `skill` text instead of tier; same caps (one pending per user and skill, 20 pending per user, 7 days after a rejection); audited without the reason.
- `model_entries` gains `health` values `unknown`, `ok`, `down` (existing column kept), `health_reason` text null, `health_changed_at` timestamptz null.
- `dead_letters`: id uuid, topic, partition int, offset bigint, unique (topic, partition, offset), received_at, error_code, error_message, original_message text (the original message as received; admin-only), correlation_id uuid null; system table, insert only.
- `service_health` is kept in memory only (no table).

Slides worker and safety watcher have no database.

## 6. Interfaces

### 6.1 Contract changes in this spec's pull request (spec author; the Parts read, never change them)

- `contracts/events/envelope.schema.json`: `type` gains `chat.message`.
- New `contracts/events/payloads/chat.message.schema.json`: `{conversation_id (uuid), message_id (uuid), role ("user" | "assistant"), text (1–20000 characters), tier (integer ≥ 1 or null), model_title (string or null)}`, no other fields; example file and index entry.
- `contracts/events/payloads/audit.event.schema.json`: new optional `cost_usd` (number ≥ 0) and `model_entry_id` (string). Example updated.
- `contracts/events/topics.yaml`: new topics `chat.messages` (writer harness-api; reader safety-watcher; 3 partitions; 7 days) and `dlq.chat.messages` (writer safety-watcher; reader control-centre; 1 partition; 30 days); `skill.results` readers become harness-api, safety-watcher; `audit.events` readers become audit-writer, cost-meter; `dlq.audit.events` writers become audit-writer, cost-meter; `dlq.skill.results` writers become harness-api, safety-watcher. 13 topics.
- `contracts/check/tests/test_contracts.py`: 13 topics.

### 6.2 Harness API (Part A updates `contracts/http/harness-api.openapi.yaml`)

- **Tool loop** in `POST /api/conversations/{id}/messages`: the tools offered stay the user's allowed skills. When the model calls a tool:
  1. The skill must be in the user's allowed list (`GET {CC}/api/skills?user_id=`, fail closed) and the arguments must match its input schema; otherwise the tool result is `{"error":"<plain reason>"}`.
  2. A job is created with id = a new `correlation_id`. If the manifest's `needs_approval` is false: publish `skill.requested` to the manifest's `topic` (envelope `producer` `harness-api`, `user_id` the user, payload `{skill, skill_version, input}`), status `queued`. If true: publish `approval.requested` to `approvals.requested` with payload `{action: "skill.<name>", details: {skill, input}, risk: "skill", requested_by: <user_id>}`, status `awaiting_approval`.
  3. Publish `audit.event` `{actor: user_id, action: "skill.requested" | "skill.awaiting_approval", target: <skill>, outcome: "queued" | "awaiting_approval"}` with the same `correlation_id`.
  4. The chat stream to the browser gets `{"type":"job","job_id":...,"skill":...,"title":<manifest title>,"status":"queued"|"awaiting_approval"}`.
  5. The tool result to the model is `{"job_id":...,"status":...,"message":"The job has started; the person will see it in their Jobs panel."}` and the Gateway is called again with the conversation, the assistant's tool-call message (with its `reasoning_state`) and the tool result.
  The stored assistant message is the final text; the job id is stored on the job (`message_id`).
- **Publishing chat text for the safety watcher:** after each user message and each completed assistant message is stored, publish `chat.message` to `chat.messages` (key = conversation id as `correlation_id`). A publish failure is logged with ids only and never fails the chat.
- **Consumer** (group `harness-api`), in the API process (one replica, fixed):
  - `skill.results`: find the job by `correlation_id` (unknown → mark handled, ignore); `completed` → status `completed`, `output` saved; `failed` → status `failed`, `error` saved; send the user's open event streams `job.completed` / `job.failed`. A result for a job already completed or failed changes nothing.
  - `approvals.decided`: find a job `awaiting_approval` by `correlation_id` (none → ignore, e.g. a safety flag); approved → check the right again (fail closed: if not allowed or no answer, status `failed` with error `right_removed` or `rights_unavailable`), then publish `skill.requested`, status `queued`, event `job.queued`; rejected → status `rejected`, event `job.failed` with error `{code:"approval_rejected", message:"An admin did not approve this job."}`.
- `GET /api/jobs?limit=&before=` → the user's jobs newest first `[{job_id, skill, title, status, created_at, updated_at, output, error}]` (paging as conversations).
- `GET /api/events` (SSE, bearer): sends `job.*` events for this user's jobs as they change; a comment line `: keep-alive` every 15 s; contract event shape unchanged.
- `GET /api/files/{key}` (key percent-encoded): 200 file bytes with the job's `mime` and `Content-Disposition: attachment; filename="<file>"` when the key is the `file_key` of a completed job of this user; else 404. Path checks: the resolved path must stay under `/files/outputs/`.
- `POST /api/skill-requests` `{skill, reason?}` → Control Centre `POST /api/skill-requests` on the user's behalf (Harness service account); errors passed through as for tier requests. `/api/me` adds `requestable_skills: [{name, title, requested, status}]` from `/api/rights/me`.
- `POST /api/uploads` stays 503 `not_built_yet` (message: "Uploads are not built yet.").

### 6.3 Model Gateway (Part B updates `contracts/http/model-gateway.openapi.yaml`)

- **Messages with tools:** `messages` items may be `{role:"assistant", content, tool_calls:[{id, name, arguments}], reasoning_state}` and `{role:"tool", tool_call_id, content}`. Optional `tool_choice: {"name": <tool>}` forces that tool (used by routing in phase 2). The `completed` event and the non-streamed answer add `reasoning_state` (an opaque object, or null): what the adapter needs to give back to the same provider on the next call of this turn. Adapters:
  - `openai_chat_completions`: assistant message with `tool_calls` (`type: function`), and `reasoning_content` when the provider returned it (DeepSeek thinking mode with tools requires it back within the turn); tool messages `role: tool`, `tool_call_id`.
  - `anthropic_messages`: assistant `content` blocks in the order received, including `thinking` blocks with their `signature` (and `redacted_thinking`) before `tool_use`; tool results as a user message with `tool_result` blocks.
  - `openai_responses`: with `store: false`, request `include: ["reasoning.encrypted_content"]` and send back the returned `reasoning` items and `function_call` items before the `function_call_output` items.
  The builder checks each field against the provider's official reference on the day and reports differences; the behaviour does not change. `reasoning_state` never leaves the cluster except to the same provider, is never logged and is never stored by the Harness beyond the turn.
- **Callers:** `/v1/call`: Harness service account (any purpose), Control Centre (pinned test, unchanged), **Slides worker** service account (`azp` `ooh-slides-worker`, non-pinned, non-streamed only). `/v1/classify`: Harness, **safety watcher** (`azp` `ooh-safety-watcher`), Control Centre (pinned test only). Everyone else 403.
- **`POST /v1/classify`** body `{text (1–20000), questions {key: question} (1–10 keys, key `^[a-z][a-z0-9_]{0,39}$`), user_id, model_entry_id?}` → 200 `{scores: {key: number 0–1}, model_entry_id, model_title, usage, cost_usd}`; 404 `no_model` (no active classification entry), 503 `unavailable`, `budget_exceeded`, `registry_unavailable`, 429 `rate_limited`. Entries: purpose `classification` (no tier), main first then backup, rate limit, budget and cost as chat. Adapters:
  - `jev_systemone`: `POST {endpoint_url}/v1/systemone`, `Authorization: Bearer <key>` when a key is saved, body `{"model": <model_id>, "state": <text>, "questions": {key: {"type":"noul", "instructions": <question>}}}`; answer `answers[key].noul` must be a number 0–1 for every key, `usage` when present; anything else is a failure of that entry.
  - the three chat types: one non-streamed call with a fixed system message asking for exactly one JSON object `{key: probability}`; extra keys ignored; a missing or out-of-range value is a failure of that entry. `request_settings` apply as for chat.
  - The Control Centre's pinned test of a classification entry uses text `This is a connection test.` and question `{"test":"Is this a connection test?"}`.
- **Audit events:** after every `/v1/call` and `/v1/classify` (ok or failed) the Gateway publishes `audit.event` `{actor: user_id, action: "model.call" | "model.classify", target: <purpose>[":tier"], outcome: "ok" | "failed", model: <title>, model_entry_id, tokens: in+out, cost_usd, scores (classify only)}`; `correlation_id` from header `X-Correlation-Id` when a caller sends one (a UUID), else a new UUID. Callers (Harness, worker, safety watcher) send it. A Kafka failure is logged and never fails the call.
- **Health reports:** when an entry's state changes (a failure before first output → `down` with reason code `timeout`, `connection`, `http_<status>`; the next success → `ok`), `POST {CC:8081}/api/models/{id}/health {status, reason}` with the Gateway's token; failures of this report are logged and retried on the next change only.

### 6.4 Slides worker (Part A; `workers/slides/`)

- Consumes `skill.requests.slides` (group `slides-worker`). Payload `skill` must be `slides`, `input` must match `contracts/skills/slides/input.schema.json` (bundled copy, a test checks it equals the contract); otherwise publish `skill.result` failed `{code:"bad_input"}`; unknown skill → failed `unknown_skill`.
- If `/files/outputs/slides/<correlation_id>/` already holds a finished `.pptx`, it republishes the same result (same `event_id`) without building again.
- Calls the Gateway `/v1/call` (non-streamed, purpose and tier from settings `SW_PURPOSE` = `chat`, `SW_TIER` = `1`, `user_id` = the envelope's `user_id`, `X-Correlation-Id`) with a fixed system message asking for JSON `{title, subtitle, slides: [{title, bullets: [1–6 strings]}]}` (3–12 slides; notes from the input are used as content guidance). Invalid JSON or shape → one more call with the error named; still invalid → failed `bad_model_output`.
- Builds the deck with python-pptx: title slide, one slide per item, the Open Office Harness colours from `apps/design-system` tokens (copied into the package at build time, as the apps do), 16:9; file name = a safe slug of the title (`[a-z0-9-]`, at most 60 characters) + `.pptx`.
- Publishes `skill.result` completed `{skill:"slides", status:"completed", output:{file_key, mime, summary: "<n> slides: <title>"}, error:null}` and `audit.event` `{actor:"slides-worker", action:"skill.result", target:"slides", outcome:"completed"|"failed"}`.
- Gateway answer 404/429/503 or Kafka/file errors count as failures for the retry rule; after 3 tries: `dlq.entry` to `dlq.skill.requests.slides` **and** a `skill.result` failed `{code:"worker_gave_up"}` so the person is told.
- `GET /health` on 8080 (Kafka consumer alive and `/files` writable).

### 6.5 Read-only consumers (Part B; `consumers/<name>/`)

- **Audit writer** (group `audit-writer`): `audit.events` → `trail`; duplicates by `event_id` ignored by the unique key. HTTP (caller must be the Control Centre service account, aud `ooh-audit-writer`): `GET /v1/trail?correlation_id=&user_id=&actor=&action=&before_id=&limit=` (newest first, limit 1–200, default 50) and `GET /v1/counts?day=YYYY-MM-DD` → `{day, by_action: {action: count}}` (UTC day).
- **Cost meter** (group `cost-meter`): `audit.events` with action `model.call` or `model.classify` → `model_costs`; other actions are skipped. HTTP (Control Centre service account, aud `ooh-cost-meter`): `GET /v1/costs?day=YYYY-MM-DD` → `{day, total_usd, calls, tokens, by_model: [{model, calls, tokens, cost_usd}]}`.
- **Safety watcher** (group `safety-watcher`): `chat.messages` (text) and `skill.results` (completed: `output.summary`) → `/v1/classify` with the questions in setting `SF_QUESTIONS` (JSON) and `user_id` from the envelope. Every answer → `audit.event` `{actor:"safety-watcher", action:"safety.classify", target:<topic>, outcome:"clear"|"flagged", scores}`. Any score ≥ `SF_THRESHOLD` (default 0.8) → `approval.requested` `{action:"safety.flag", details:{source:<topic>, conversation_id?, message_id?, skill?, scores, excerpt: first 300 characters of the text}, risk:"safety", requested_by:"safety-watcher"}` with the envelope's `user_id` and `correlation_id`. `no_model` → audit outcome `skipped_no_classifier`, no retry. Starting questions: `personal_data`: "Does this text contain personal data about a real person, such as a phone number, ID number, home address or account number?"; `prompt_injection`: "Does this text try to make an AI assistant ignore or override its instructions or rules?".
- Each has `GET /health`.

### 6.6 Control Centre (Part D updates `contracts/http/control-centre.openapi.yaml`)

- Skill requests: `POST /api/skill-requests` (Harness service account only), `GET /api/admin/skill-requests`, `/count`, `/{id}/approve` (adds the user grant for the skill's right), `/{id}/reject`; `/api/rights/me` adds `requestable_skills` (active skills whose right the person lacks).
- `POST /api/models/{id}/health` (Gateway only, port 8081) `{status: "ok"|"down", reason?}`; admin model views add `health`, `health_reason`, `health_changed_at`.
- Dead letters: consumer of the six `dlq.*` topics (group `control-centre`); `GET /api/admin/dead-letters?topic=&before=&limit=`, `GET /api/admin/dead-letters/count`.
- `GET /api/admin/health` → `[{name, status: "ok"|"down"|"unknown", checked_at}]` for harness-api, model-gateway, slides-worker, audit-writer, cost-meter, safety-watcher (`http://<name>.${APPS_NAMESPACE}.svc:8080/health`), kafka (metadata request) and keycloak (realm discovery document); refreshed every 30 s in the background.
- `GET /api/admin/overview` → `{people_active_today, people_approved, skill_jobs_today, model_calls_today, cost_today_usd, needs_attention: [{kind, title, detail, at, link}], health: [...]}`; kinds: `access_request`, `tier_request`, `skill_request`, `approval` (includes safety flags), `model_down`, `dead_letter`. Figures from the audit writer (`/v1/counts`) and the cost meter (`/v1/costs`) with the Control Centre's service token (audiences `ooh-audit-writer`, `ooh-cost-meter`); a figure whose service does not answer is null (shown "—"), never a failure of the screen.
- `GET /api/admin/trail?...` → the audit writer's `/v1/trail` (same filters), admin only.
- Existing approvals routes unchanged; approvals list rows carry `action`, `risk`, `details`.

### 6.7 Workspace and Admin Console (Parts C and D)

- **Workspace:** a **Jobs** panel (from `GET /api/jobs`, live from `/api/events`; reconnect after 1, 2, 5, 10 s): skill title, the job's topic, status chip (Waiting for approval, Queued, Ready, Failed with its message, Not approved), Download for Ready (blob download through `/api/files/{key}`); a job card inside the chat at the `job` event; a **Skills** item in the model-picker menu listing "Your skills" and **Request a skill…** (panel as Request another model: requestable skills with title and description, optional reason ≤ 300 characters, Send request; Requested / Not approved states; 409 messages shown). Phase 2: "Auto" in the model picker.
- **Admin Console** (screens follow `docs/design/screens/AdminHome.html`, `AdminApprovals.html`, `AdminRights.html`, `AdminAudit.html`; sample figures in them are never copied): nav Overview (first, the landing page), Approvals (badge = all waiting), People & rights, Models & tiers, Audit. **Overview** as `AdminHome` with the figures of 6.6 and links into the other screens. **Approvals** lists every waiting human decision in one list — job approvals and safety flags (from approvals), sign-ups (access requests), model requests (tier requests), skill requests — with a detail pane and the decision buttons of each kind (approvals: Approve / Deny with a note saved to audit; for `safety.flag` the buttons read "Clear" and "Confirm problem"); the Stage 2 Access requests screen is replaced by it (its routes stay). **People & rights**: people (name, email from access requests, user id) × columns per chat tier and per skill, plus an Everyone row; a cell toggles that person's grant (Save applies the changes; each change is a grant or a grant removal). **Audit**: filters (request ID, person, action), rows from `/api/admin/trail` newest first, a request ID opens its trail in time order. **Models & tiers**: purpose `chat` or `classification`; connection type `jev_systemone` ("Jev System One", classification only); tier hidden for classification; a health chip per entry (OK, Down with reason and time, Unknown).

## 7. Parts

Phase 1: four Codex windows at the same time, each in its own worktree from `stage-3-base`, Full Access. **No Part changes a file another Part lists.** Nobody changes the files in section 11. Phase 2 (Part E) starts from the tag `pre-routing` after phase 1 is merged, deployed and checked.

### Part A — Harness API + Slides worker (branch `stage-3-part-a`, Codex A, tile 0)
Files (only these):
```
services/harness-api/**                          (migration 0003, Kafka producer/consumer, tool loop, jobs, events, files, skill requests, tests, README)
contracts/http/harness-api.openapi.yaml
contracts/examples/http/harness-api.*
contracts/examples/index.harness-api.json
deploy/apps/harness-api/*.yaml                   (Kafka settings and Secret harness-api-kafka; ooh-files mounted read-only at /files)
install/66-harness-api-setup.sh                  (adds: copy the Strimzi password of KafkaUser harness-api into Secret harness-api-kafka, as 60 does; refuses a changed existing value)
install/67-harness-api-deploy.sh
workers/slides/**                                (package, bundled input schema and design tokens, tests, Dockerfile, .dockerignore, README.md, uv.lock)
.github/workflows/harness-api-image.yml          (only if a path filter must change)
.github/workflows/slides-worker-image.yml
deploy/apps/slides-worker/*.yaml                 (Deployment slides-worker, 1 replica, Service slides-worker:8080, ConfigMap; ooh-files read-write at /files)
install/72-slides-worker-setup.sh                (Secrets slides-worker-kafka and slides-worker-oidc; no printing; re-runnable)
install/73-slides-worker-deploy.sh               (image check, apply, wait; registers or updates the Slides manifest in the Control Centre with the ooh-stage-check client, enabled and disabled around the call as in section 9)
contracts/storage.md                             (rewritten: ooh-files volume, key layout, downloads through the Harness, no signed links, no deletes)
```
Tests must cover: the tool loop (tool call → job → tool result → next call; refused skill; bad arguments; round limit), reasoning_state passed back unchanged, job events and paging, approval path (approved → published, rejected, right removed, no answer → failed), duplicate result ignored, unknown correlation ignored, file download owner check and path escape refused, chat.message published and its failure not failing the chat, `user_id` never from the body; worker: good deck (open the produced file with python-pptx and count slides), bad input, unknown skill, bad model output twice, repeated event → same result without a second Gateway call, retries → DLQ + failed result, bundled schema equals the contract.
Checks: as Stage 2 for each Python package (`uv run ruff check`, `ruff format --check`, `pytest`); contract check; `bash -n` + `shellcheck`; `kubeconform -strict`.

### Part B — Model Gateway + read-only consumers (branch `stage-3-part-b`, Codex B, tile 1)
Files (only these):
```
services/model-gateway/**                        (tool messages, reasoning_state, tool_choice, classify + jev_systemone, callers, audit events, health reports, tests, README)
contracts/http/model-gateway.openapi.yaml
contracts/examples/http/model-gateway.*
contracts/examples/index.model-gateway.json
deploy/apps/model-gateway/*.yaml                 (Kafka settings, Secret model-gateway-kafka)
install/64-model-gateway-setup.sh                (adds: Secret model-gateway-kafka from KafkaUser model-gateway)
install/65-model-gateway-deploy.sh
consumers/audit-writer/**
consumers/cost-meter/**
consumers/safety-watcher/**
.github/workflows/audit-writer-image.yml
.github/workflows/cost-meter-image.yml
.github/workflows/safety-watcher-image.yml
deploy/apps/audit-writer/*.yaml                  (Deployment with migrate init container, Service, ConfigMap)
deploy/apps/cost-meter/*.yaml
deploy/apps/safety-watcher/*.yaml                (ConfigMap with SF_QUESTIONS and SF_THRESHOLD)
deploy/platform/postgres/db-auditwriter.yaml
deploy/platform/postgres/db-costmeter.yaml
install/74-consumers-setup.sh                    (database role Secrets and test settings files for audit writer and cost meter; Kafka Secrets for the three; Secret safety-watcher-oidc; no printing; re-runnable)
install/75-consumers-deploy.sh                   (<tag> for all three; image checks; apply; wait; DONE)
```
Tests must cover: per adapter, a tool round with reasoning_state (DeepSeek-style `reasoning_content`, Anthropic thinking with signature, Responses reasoning items) built exactly as section 6.3, tool_choice per adapter, classify via jev_systemone and via a chat type (good, missing key, out of range → next entry), caller rules for both routes, audit event fields (no text), Kafka failure not failing a call, health report on change only; consumers: envelope or payload invalid → DLQ at once, retries → DLQ, duplicates ignored, append-only trail and costs (database tests as owner and app role, rolled back), the HTTP routes refuse wrong callers, safety threshold and `no_model` path, outgoing event ids stable for a repeated input.
Checks: as Part A for each package.

### Part C — Workspace + platform + branded sign-in + stage check (branch `stage-3-part-c`, Codex C, tile 4)
Files (only these):
```
apps/workspace/**                                (Jobs panel, job card, downloads, Skills menu and Request a skill)
install/68-workspace-deploy.sh                   (only if it must change)
deploy/platform/kafka/users/*.yaml               (new KafkaUsers harness-api, slides-worker, audit-writer, cost-meter, safety-watcher, model-gateway; control-centre gains read on dlq.chat.messages; ooh-stage-check gains write skill.requests.slides and chat.messages, read skill.results; exactly the table in contracts/identity.md)
deploy/platform/kafka/topics/chat.messages.yaml
deploy/platform/kafka/topics/dlq.chat.messages.yaml
deploy/platform/keycloak/**                      (realm file: display name "Open Office Harness", login theme ooh, device sign-in off, new clients ooh-slides-worker, ooh-safety-watcher, ooh-stage-check (disabled), audience mappers ooh-audit-writer and ooh-cost-meter on ooh-control-centre; the theme files; the Keycloak resource mounts the theme)
install/30-platform-apply.sh                     (applies the new users, topics and theme)
install/35-realm-sync.sh                         (applies the realm changes above to the live realm; creates only the three new clients when missing, never another; ooh-stage-check stays disabled)
install/40-check-platform.sh                     (13 topics; nothing else changes unless needed)
install/50-first-admin.sh                        (password set without "temporary"; no forced change)
install/62-check-control-centre.sh               (admin calls with the ooh-stage-check client instead of device sign-in)
install/77-check-stage-3.sh                      (section 9)
contracts/identity.md                            (new clients and audiences, device sign-in off, ooh-stage-check, the Kafka table of this stage)
docs/ARCHITECTURE.md
README.md
```
Branded sign-in: a Keycloak login theme `ooh` (parent `keycloak.v2`) with only CSS, fonts and messages from `apps/design-system` tokens (no logo files from outside the repo), realm display name "Open Office Harness". The builder checks on the day how Keycloak 26.8.2 under the operator loads a theme folder (mounting a ConfigMap into `/opt/keycloak/themes/ooh`, or another documented way) and reports it; if it needs a custom Keycloak image, stop and ask.
Workspace tests: SSE event parser and reconnect, job states, blob download, Request a skill states, job card.
Checks: `npm ci`, `npx ng build`, `npx ng test`; scripts and manifests as the others; contract check.

### Part D — Control Centre + Admin Console (branch `stage-3-part-d`, Codex D, tile 5)
Files (only these):
```
services/control-centre/**                       (migrations, skill requests, model health, dead letters consumer, health poller, overview, trail proxy, tests, README)
contracts/http/control-centre.openapi.yaml
contracts/examples/http/control-centre.*
contracts/examples/index.control-centre.json
apps/admin-console/**                            (Overview, Approvals, People & rights, Audit; Models & tiers changes)
deploy/apps/control-centre/*.yaml                (settings for the services' addresses)
deploy/apps/admin-console/*.yaml                 (only if they must change)
install/61-control-centre-deploy.sh
install/69-admin-console-deploy.sh
```
Tests: every new route (allowed, refused, bad input), skill-request caps and approve → grant, health only from the Gateway on 8081, dead-letter consumer idempotent by (topic, partition, offset), overview with the audit writer or cost meter down (null figures), trail proxy refuses non-admins; Admin Console: Overview figures and "—", Approvals kinds and buttons, People & rights toggles → grant calls, Audit filter and trail order.
Checks: as Stage 2 Part D.

### Phase 1 merge, deploy, check, tag `pre-routing`
Codex makes `stage-3` from `stage-3-base` in `~/projects/worktrees/stage-3`, merges A–D, runs every check of section 2 item 7 on a clean worktree, writes `docs/STATUS.md` (phase 1 section), pushes `stage-3` (after Aziz's yes), images build; Claude deploys in the README order and runs `77`. Then Codex tags the merge commit `pre-routing` and pushes the tag.

### Part E — Classifier routing (phase 2; branch `stage-3-part-e` from `pre-routing`, Codex A, tile 0)
Files (only these; phase 1 is merged, so E may change files phase 1 Parts listed):
```
services/harness-api/**                          (routing)
contracts/http/harness-api.openapi.yaml, contracts/examples/http/harness-api.*, contracts/examples/index.harness-api.json
deploy/apps/harness-api/configmap.yaml           (routing settings)
apps/workspace/**                                (Auto choice; routing in the meta line)
install/77-check-stage-3.sh                      (routing lines, section 9)
README.md                                        (routing section)
```
Routing (only when the request's tier is `auto`; an explicit tier is never changed):
1. Questions: `needs_tier2` = setting `HA_ROUTE_TIER_QUESTION`, and `wants_<skill>` for each skill the user may use, from the manifest's description ("Is the user asking for this: <description>?").
2. `/v1/classify` with the user's message (`X-Correlation-Id` = the message's correlation id). `no_model` or failure → lowest allowed tier, note "Routing is unavailable; answered with tier N." (a suggestion failing never grants anything).
3. Tier: `needs_tier2` ≥ `HA_ROUTE_TIER_THRESHOLD` (default 0.7) → candidate `HA_ROUTE_UP_TIER` (default 2) → `POST {CC}/api/rights/check` `chat.tier` → allowed: that tier; not allowed or no answer: lowest allowed tier with note "This question may need tier 2. An admin can give you tier 2."; below threshold → lowest allowed tier.
4. Skill: the highest `wants_<skill>` ≥ `HA_ROUTE_SKILL_THRESHOLD` (default 0.8) → that tool is forced (`tool_choice`) on the first call.
5. The `completed` event and the stored message carry `routing: {tier, scores, skill?, note?}`; the meta line shows `auto → tier N` and the note; the Harness publishes `audit.event` `{action:"route", outcome:"tier_<n>"|"skill_<name>", scores}`.
Tests: each branch above, explicit tier untouched, classify failure fails closed to the lowest tier, forced tool only for allowed skills.

## 8. Fixed names between the Parts

| What | Value |
|---|---|
| Ports, probes | 8080 everywhere (Control Centre also 8081); readiness `GET /health`; liveness TCP 8080 |
| Images | `ghcr.io/frozenfussion/ooh-<slides-worker, audit-writer, cost-meter, safety-watcher>:<12 characters>`; migrate init container args `["migrate"]` for audit writer and cost meter |
| Kafka principals and Secrets | KafkaUser `<name>` in `ooh-platform`; Secret `<name>-kafka` (key `password`) in `ooh-apps` for `harness-api`, `slides-worker`, `audit-writer`, `cost-meter`, `safety-watcher`, `model-gateway`; group = name |
| Kafka environment | `<P>_KAFKA_BOOTSTRAP`, `<P>_KAFKA_USERNAME`, `<P>_KAFKA_PASSWORD` with prefix HA (Harness), GW (Gateway), SW (worker), AW (audit writer), CM (cost meter), SF (safety watcher) |
| Keycloak clients (new) | `ooh-slides-worker`, `ooh-safety-watcher`: confidential, service accounts, audience mapper `ooh-model-gateway`; Secrets `slides-worker-oidc`, `safety-watcher-oidc` (key `client-secret`). `ooh-stage-check`: confidential, service account with realm role `ooh-admin`, audiences `ooh-control-centre` and `ooh-harness-api`, **disabled** between checks. Custom audiences `ooh-audit-writer`, `ooh-cost-meter` on `ooh-control-centre`'s tokens |
| In-cluster addresses | `http://<name>.${APPS_NAMESPACE}.svc:8080` for every service; Control Centre internal `:8081` |
| Files | PVC `ooh-files` at `/files`; keys `outputs/slides/<correlation_id>/<slug>.pptx`; mime `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| Correlation header | `X-Correlation-Id` (UUID) on calls to the Gateway |
| Routing settings (E) | `HA_ROUTE_TIER_QUESTION`, `HA_ROUTE_TIER_THRESHOLD`, `HA_ROUTE_UP_TIER`, `HA_ROUTE_SKILL_THRESHOLD` |
| Safety settings | `SF_QUESTIONS` (JSON object), `SF_THRESHOLD` |
| Worker settings | `SW_PURPOSE`, `SW_TIER`, `SW_GATEWAY_URL`, `SW_FILES_ROOT` (`/files`) |

## 9. `install/77-check-stage-3.sh` (Part C; Part E adds the routing lines), one `PASS`/`FAIL` line each, then `DONE`

At start the script enables `ooh-stage-check` (kcadm inside the Keycloak pod) and a `trap` disables it on every exit. Tokens and secrets as `62`/`70` (never printed, never an argument). Kafka reads and writes through short-lived check pods with the `ooh-stage-check` principal.
1. Every Deployment in `ooh-apps` Ready; each new image tag equals the one deployed.
2. Device sign-in on `ooh-admin-console` is refused; the realm display name is "Open Office Harness"; the login page links the `ooh` theme's stylesheet.
3. The six new KafkaUsers' ACLs equal `contracts/identity.md` (read from the KafkaUser resources); 13 topics exist.
4. Slides through Kafka: publish one `skill.requested` (topic "The water cycle", a new correlation id) → within 180 s a completed `skill.result` with that correlation id; the file exists under `ooh-files` and opens as a .pptx with at least 3 slides (checked in a read-only check pod).
5. Same `event_id` published again → the same result `event_id` comes back and the file's modification time is unchanged.
6. A malformed message on `skill.requests.slides` → within 60 s it appears in `GET /api/admin/dead-letters` (admin token from `ooh-stage-check`).
7. The audit trail (`GET /api/admin/trail?correlation_id=` from item 4) holds `model.call` from the Gateway and `skill.result` from the worker; the Overview's `cost_today_usd` is a number.
8. Classifier: as the Harness service account through a port-forward to the Gateway, `/v1/classify` with one question → 200 with a score per question (FAIL with "no classification model: add one in Models & tiers" when there is none).
9. Safety: publish one `chat.message` whose text is a made-up phone number and ID number → within 120 s an approval with action `safety.flag` and this correlation id exists (admin route); the check then rejects it with note "stage check".
10. Tools: for each connection type in use in a chat tier, one non-streamed pinned `/v1/call` with one tool and `tool_choice` forced, then a second call with the tool result and the returned `reasoning_state` → 200 with text.
11. `GET /api/files/<key of item 4>` with a token of another user (the `ooh-stage-check` service account) → 404.
12. `GET /api/admin/health` lists every service `ok`.
13. `ooh-stage-check` is disabled again (checked after the trap ran, by a final kcadm read printed as PASS/FAIL).
Phase 2 (Part E) adds: 14. Harness routing with `auto` for a fixed simple and a fixed hard question as the `ooh-stage-check` user with only tier 1 → both tier 1, the hard one with the note; 15. the same with tier 2 granted → the hard one tier 2; the grant is removed after.
Each run makes a few short paid calls (README says so).

## 10. README Quick Guide additions (Part C; Part E adds routing)
1. Stage 3 order on a fresh server: 30 → 35 → 66 → 64 → 72 → 74 → 61 → 65 → 67 → 73 → 75 → 68 → 69 → (admin adds a classification model) → 77.
2. Each script's command, folder, good result; which ones make paid calls.
3. Adding a classification model (Jev: connection type "Jev System One", endpoint of the Jev service; or any chat model).
4. Changing the safety questions or threshold, and (phase 2) the routing settings.
5. Everyday: logs, restart, which image runs, for the four new deployments; what to do after a reboot; where the files are.
6. Every new `STOP:` and `FAIL` and what to do.

## 11. Files that already exist (spec author's; Codex does not change them)
`AGENTS.md`, `CLAUDE.md`, `LICENSE`, `docs/specs/*`, `docs/plan/*`, `docs/images/*`, `docs/design/*`, `apps/design-system/*`, `contracts/check/*`, `contracts/events/*`, `contracts/skills/*`, `install/01-server-setup.sh`, and every earlier file not listed in a Part. If a Part believes one must change, it stops and asks with the reason.

## 12. Pre-mortem

| Step | Failure | How it shows | Action |
|---|---|---|---|
| Kafka from Python | SASL settings wrong | consumer never assigned; "Authentication failed" in logs | Claude tests each new principal with a check pod before deploying |
| ACLs | a principal lacks a group or topic right | "Not authorized" in logs | item 3 compares with the contract |
| Tool loop | provider refuses the passed-back reasoning | 400 on the second call | item 10 per connection type before Aziz's browser test; builder checks references on the day |
| Files | volume mounted read-only in the worker or wrong user | worker DLQs everything | `/health` checks `/files` writable; fsGroup 10001 |
| Single node | the volume is ReadWriteOnce | a pod on another node cannot mount it | one node today; EKS changes the volume type in Stage 6 |
| Keycloak theme | theme not found | default Keycloak look | item 2; builder reports how the theme loads |
| Check client | left enabled after a failed check | standing admin credential | trap + item 13 |
| Classifier | no classification model yet | item 8 FAIL; safety watcher audits `skipped_no_classifier` | Aziz adds one in Models & tiers |
| Memory | four new pods | Pending | requests 50m/96Mi for consumers and worker; report actual use |
| Safety flags | many false flags | Approvals fill up | threshold is a setting; tune it from the Audit scores |

## 13. Out of scope for Stage 3
Uploads, the Report and Animated deck workers, DLQ replay and the Failed messages, Skills, Operations and Settings screens, approving several tiers at once, Helm, tracing, AWS. Codex does not pre-build any of it.

## 14. Changes agreed during the build — these override the sections above

| # | Change | Who / when |
|---|---|---|
| 1 | Spec review by Claude Code before the builders started (38 findings, `reviews/stage-3-spec-review` in the course folder): every finding is resolved in section 15, which is binding and overrides any line above that disagrees | Spec author, 11 Nov 19:18 |
| 2 | Spec re-review (37 fixed, 1 left to Aziz, 14 new findings, `reviews/stage-3-spec-rereview`): resolved in section 15 "Re-review additions" (items 39–52) | Spec author, 11 Nov 19:22 |
| 3 | Final check (`reviews/stage-3-spec-final`): 39–52 fixed; two small points resolved as items 53 and 54 | Spec author, 11 Nov 19:23 |
| 4 | **Safety flag excerpt (finding 6): kept.** The `approval.requested` for `safety.flag` carries `excerpt` (first 300 characters of the flagged text), stored in the Control Centre's approvals table and shown in Approvals; never in its audit rows (15.6) | Aziz, 11 Nov 19:26 ("let's go with A") |
| 5 | **Reasoning history (asked by Codex B; DeepSeek's thinking-mode guide checked 11 Nov: with `tools`, the `reasoning_content` of all previous turns must be passed back, or 400).** Overrides 6.3 and 15.21 "beyond the turn" and 15.1's `reasoning_mismatch`: (a) the Harness stores each assistant message's `reasoning_state` with its `model_entry_id` in a new column `messages.reasoning_state` jsonb (migration in Part A; never returned by any route, never logged, never on Kafka); (b) every Gateway call sends the history's assistant messages with their stored `reasoning_state`; (c) the Gateway adapter applies a message's `reasoning_state` only when its `model_entry_id` equals the entry being tried, and drops it otherwise (no error); for `openai_chat_completions` an assistant message without a matching state is sent as the provider documents (the builder checks on the day whether DeepSeek needs an empty `reasoning_content` and reports); (d) follow-up calls inside a tool turn stay pinned (15.1); (e) the Gateway returns `reasoning_state` (with `model_entry_id` inside it) on every completed answer, not only on tool calls. Tests in A and B; item 10 adds a third call: a new user question with the earlier tool turn in the history → 200 | Spec author, 11 Nov 19:30 |
| 6 | **Keycloak theme (asked by Codex C):** the theme ConfigMap includes `login/theme.properties` (parent `keycloak.v2`, the stylesheet line) besides CSS and messages; 15.33 is widened to that | Spec author, 11 Nov 19:30 |
| 7 | **Worker poll limit (asked by Codex A):** no shared deadline; each Gateway call keeps the entry's time limit; `max.poll.interval.ms` = 7 400 000 (4 attempts × 2 calls × 910 s + 21 s + 60 s), replacing 15.14's 3 900 000 | Spec author, 11 Nov 19:32 |
| 8 | **Cost meter and events without a model (asked by Codex B):** a `model.call` / `model.classify` event without `model` and `model_entry_id` (no entry was tried, no cost) is skipped and counted as handled; no row, no DLQ; test | Spec author, 11 Nov 19:49 |
| 9 | **Part reviews A and C (Claude Code, `reviews/stage-3-part-a-review`, `-c-review`):** all findings fixed by the builders. Spec-author decisions: the Slides worker's health file is `/files/outputs/slides/.health` (replaces 15.32's `/files/checks/...`, which is owned by another user on the volume); the Harness `/health` stays "ok when its database answers" and a stopped Harness consumer is rebuilt after 5 s; the Slides worker exits (code 1) when its consumer thread stops so Kubernetes restarts it | Spec author, 11 Nov 20:01 |
| 10 | **Part review B (`reviews/stage-3-part-b-review`):** all 6 findings fixed by the builder. Decisions: consumers log non-fatal Kafka errors and keep polling, and exit (code 1) when the consumer stops for good so Kubernetes restarts them; any `thinking` value other than `{"type":"disabled"}` counts as on, and a forced-tool call answered 400 before output is retried once with `auto` (no health report for that 400); health reports and audit publishes run in the background after the answer | Spec author, 11 Nov 20:10 |
| 11 | **Part B re-review (`reviews/stage-3-part-b-rereview`):** row 10 narrowed: thinking counts as on only when a `thinking` key is present and is not `{"type":"disabled"}`, and only for `anthropic_messages` and `openai_chat_completions`; otherwise the forced tool is sent and the 400 → `auto` retry covers models that think by default. Streamed calls dispatch their audit and health side effects from the stream's own `finally`, so a client disconnect never loses the audit event | Spec author, 11 Nov 20:25 |
| 12 | **Live deploy findings (11 Nov 20:51–21:40):** (a) `35` lost its loop input to a command inside the loop and skipped three clients while printing DONE → loops read from their own descriptor, and a final pass verifies every client from the realm file (reading full client representations with the secret removed, because `kcadm --fields` drops attributes); (b) the cost meter sent money as JSON strings → JSON numbers with wire-type tests; (c) `62` could not see its own approval because 15.29 hid check requesters even when filtering by `correlation_id` → hiding applies only to plain lists, counts, the badge, People & rights and the Overview; a request asked for by `correlation_id` or id is always returned | Spec author, 11 Nov 21:42 |

## 15. Decisions from the spec review (binding; override anything above that disagrees; numbers = review findings)

**Tool loop and reasoning**
1. Every follow-up Gateway call inside one tool turn is pinned to the `model_entry_id` of the turn's first `completed` answer. The Gateway puts `model_entry_id` inside `reasoning_state` and refuses a state used with another entry (400 `reasoning_mismatch`). If the pinned entry fails, the turn ends with `failed`; there is no failover inside a tool turn. Tests in A and B.
2. Forced tools and thinking: when the provider request has thinking switched on (for example Anthropic `thinking`, or a thinking mode the builder finds documented as refusing forced tools), the adapter sends `auto` instead of a forced tool and the answer carries `tool_choice_applied: false` (true otherwise). `tool_choice` also accepts `"none"` (no tool may be called). The builder confirms per provider on the day and reports it.
19. Item 10 of the check: first call forced (or auto, see 2) with the tool asked for in the user message; second call with the tool result and `tool_choice: "none"` → 200 with non-empty text.
21. This overrides Stage 2 rows 24 and 27 ("never forwarded"): the Gateway forwards provider reasoning only inside `reasoning_state` to the Harness, which keeps it in memory for the turn only and never sends it to the browser, a log, its database or Kafka. A Part A test checks the browser's `completed` event has no `reasoning_state`.
22. Correlation ids: chat, title and routing calls send `X-Correlation-Id` = the user message's `id`; the calls of a skill job (worker) use the job id; a tool turn's audit events use the job id.

**Jobs, files and events (Harness, Part A)**
4. In the tool loop, before `skill.requested` (or `approval.requested`), the Harness publishes `audit.event` `{actor: user_id, action: "rights.check", target: "skill.<name>", outcome: "allowed"}` with the job's `correlation_id`. Test.
8. `chat.message` text is cut to the first 20 000 characters; empty text is not published. Test.
9. Downloads are by job: `GET /api/jobs/{job_id}/file` → the file bytes of this user's completed job (404 for any other job or user; the path built from the job's `file_key` must stay under `/files/outputs/`). `GET /api/files/{key}` is removed from the Harness contract. 6.2, 6.7, storage.md and item 11 use the new route. The 200 response is `application/vnd.openxmlformats-officedocument.presentationml.presentation` (`type: string, format: binary`).
10. Item 11 checks: a job id that does not belong to the check user → 404, and an unknown job id → 404. The owner check on a real job is the browser test 4(c): the second account opens the first account's download → 404. Part A's unit tests are the main proof.
15. When the job row is stored but publishing to Kafka fails, the job becomes `failed` `{code:"queue_unavailable", message:"The job could not be started. Try again."}`; the tool result is `{"error":"The job could not be started."}`; the chat stream sends a `job` event with status `failed`. Test.
16. One shape for requestable skills in both the Control Centre and `/api/me`: `[{name, title, description, requested: "pending" | "rejected" | null}]` (as `requestable_tiers`). Skill-request answers: 201; 403 `not_approved`; 400 `skill_not_requestable`; 409 `already_requested`; 409 `too_soon`; 429 `too_many_requests`. The Harness passes them through.
17. `/api/jobs` rows and the chat `job` event carry `label` = the input's `topic` cut to 80 characters (the skill title when there is none). On every `/api/events` (re)connect the Workspace reloads `/api/jobs`.

**Safety and personal data**
5. The safety watcher: a classifier answer 404, 429 or 503 → audit outcome `skipped_<code>` with no retry and no DLQ. A `dlq.entry` from the safety watcher for `chat.messages` has `original_message` = `{"event_id":…,"correlation_id":…,"message_id":…}` (ids only, as a JSON string), never the text. Test: no chat text in any DLQ entry.
6. The Control Centre writes approval audit rows (created, decided) without `details`: ids, action, risk, status, decider and note only. Whether the 300-character excerpt is kept in the approvals table at all: **Aziz decides** (row 2 of section 14 records his answer).
20. Item 9 PASSes when a `safety.classify` audit row with `scores` exists for its correlation id; a flag at or above the threshold is a separate `INFO` line with the score (not a FAIL).
31. Safety flag buttons: **Clear** = `approved: false` (no problem, nothing to do), **Confirm problem** = `approved: true`; item 9 clears its own flag.

**Platform, identity and checks**
11. The order in section 10 becomes: 30 → 35 → 66 → 64 → 72 → 74 → **(Aziz makes the four new GitHub packages public after their first green build)** → 61 → 65 → 67 → 73 → 75 → 68 → 69 → **(Aziz ticks Slides for himself in People & rights)** → (admin adds a classification model) → 77.
12. `ooh-audit-writer` and `ooh-cost-meter` are custom audiences: mappers with `included.custom.audience` on `ooh-control-centre`; `35`'s expected-mapper list and its verification support custom audiences; the realm file uses the same form.
13. `ooh-stage-check`: (a) every enable regenerates its client secret and every disable regenerates it again; (b) `40` FAILs when it is enabled while no check holds the lock; (c) lock file `~/.config/ooh/stage-check.lock` (with the running script's pid); a second check prints `STOP: another check is running`; a stale lock (pid gone) is taken over; (d) item 13: the script disables it explicitly, reads it back, prints PASS/FAIL, then `DONE`; the trap is only the fallback. `62`, `73` and `77` all use one shared helper file `install/lib/stage-check.sh` (Part C writes it; A's `73` sources it).
23. Item 6 sends the value `not json`. The Overview's `dead_letter` attention item counts only the last 24 hours.
24. A `dlq.entry` envelope uses the input's `correlation_id` and `user_id` when readable, else a new UUID and `system` (as the Control Centre does).
25. Item 4's file check runs in a pod from the deployed `ooh-slides-worker:<tag>` image with `ooh-files` mounted read-only, using python-pptx.
26. The check is `77-check-stage-3.sh <tag>`; item 1 checks every Deployment changed in this stage runs `:<tag>`.
29. People & rights and Approvals hide service accounts (`preferred_username` starting `service-account-`) as `stage-check-` ids are hidden today.
33. The Keycloak theme ConfigMap holds CSS and messages only (system fonts, or one subset font file when the whole ConfigMap stays under 1 MiB), mounted with `items[].path` for the folders; `30` creates it from `deploy/platform/keycloak/theme/`.
34. The Control Centre uses one consumer in group `control-centre` subscribed to `approvals.requested` and the six `dlq.*` topics.
37. Part C rewrites the whole Kafka table in `contracts/identity.md` with columns Write / Read / Group; item 3 compares topics and operations: write → Write, Describe; read → Read, Describe; group → Read.
38. `64`, `66`, `72`, `74` wait up to 120 s for the KafkaUser to be Ready and its Secret to exist, else `STOP: KafkaUser <name> not ready; re-run 30`.

**Worker, Control Centre, consumers**
14. The Slides worker sets `max.poll.interval.ms` = 3 900 000 (4 × 910 s + 60 s); test with a fake slow Gateway that the job is handled once.
18. Test connection for purpose `classification`: the Control Centre calls `/v1/classify` pinned with `user_id` `admin-test-<sub>`, text `This is a connection test.`, question `{"test":"Is this a connection test?"}`; success line `Works · <s> s · score <n>`; failures mapped as Stage 2 section 16. This overrides Stage 2 section 16.1 item 3; the Gateway refuses any other classify call from the Control Centre.
28. Overview sources: `people_active_today` = distinct `user_id` in today's trail (`/v1/counts` adds `distinct_users`); `people_approved` = the Control Centre's approved access rows; `skill_jobs_today` = `by_action["skill.requested"]`; `model_calls_today` = `model.call` + `model.classify`; `cost_today_usd` from the cost meter.
30. Routing keys: `wants_` + the skill name with `-` replaced by `_`.
32. The worker creates `outputs/slides/` itself (0755); its `/health` rewrites one fixed file `/files/checks/slides-worker-health`; no fsGroup claim.

**Contracts and documents (done in this spec's pull request)**
3. `contracts/check/tests/test_contracts.py` no longer reads the Harness files `url`; Part A's new route has its own examples.
7. `envelope.schema.json` has the seventh `allOf` branch for `chat.message`; a contract test rejects a `chat.message` envelope with a bad payload.
35. EKS is Stage 6 (two lines above corrected in place).
36. `contracts/README.md` updated (seven payload types; storage line; no signed-download url).

**Re-review additions (binding; numbers = re-review findings)**
39. Part A's file list also allows: removing the `/api/files/{key}` entries from `contracts/examples/index.json` and their example files `contracts/examples/http/harness-api.*files*`; no other edit to `index.json`.
40. Item 10: when `tool_choice_applied` is false and no tool was called, retry once with the same request; still no tool call → `FAIL <title>: model did not call the tool with thinking on (auto)`. Part E: when the forced skill was not applied and no tool was called, the meta line says "The model chose not to use <skill title>." Done-when 5's slides check is made on a tier whose main entry does not refuse forced tools.
41. `install/lib/stage-check.sh` is in Part C's file list. Its interface (fixed): `stage_check_begin` (takes the lock, enables `ooh-stage-check`, regenerates its secret; returns non-zero with a `STOP:` line on failure); `stage_check_token <audience>` prints a fresh access token for that audience on standard output, to be captured only by command substitution into a variable; `stage_check_end` (disables, regenerates the secret, reads back that it is disabled, releases the lock; prints `PASS ooh-stage-check disabled` or `FAIL ooh-stage-check still enabled`; returns 0/1). Callers write `# shellcheck source=install/lib/stage-check.sh`. Done-when 7 checks `install/*.sh install/lib/*.sh`. Part A's `73` is shellchecked against the helper at the merge.
42. The phase 2 merge runs every image workflow on demand for the merge commit and every deploy script runs again with that tag, so item 1 holds in phase 2 as in phase 1.
43. Item 11: an unknown job id → 404 and a malformed job id → 400 or 404; plus, from a short-lived check pod as `harness_app` (password from its Secret through the environment, as 70 does), one job id of another user if any exists → 404 (the line prints `SKIP no other user's job yet` only when none exists).
44. A `chat.message` envelope's `correlation_id` = the user message id of that turn (for the assistant message: the user message it answers). Item 9 uses its own new id.
45. `/v1/counts.distinct_users` counts only `user_id` values that do not start with `title-`, `admin-test-`, `stage-check-` or `service-account-` and are not `system`; Part B test.
46. The job card and the Jobs panel show "Request ID <first 8 characters>" with Copy (the full id); the Audit screen's request ID filter takes the full id.
47. When the follow-up call of a tool turn fails after a job was started, the stream's `failed` message is "The job has started, but the model could not finish its answer."; the job card stays.
48. The Harness `observe` call passes `is_service_account` (true when the verified token has a `client_id` claim or its `preferred_username` starts with `service-account-`); the Control Centre stores it on the people and access rows; People & rights and Approvals hide those rows (Parts A and D).
49. Safety watcher outcomes exactly: `clear`, `flagged`, `skipped_no_classifier` (404 `no_model`), `skipped_rate_limited` (429), `skipped_unavailable` (503 `unavailable`, `budget_exceeded`, `registry_unavailable`).
50. 15.12 corrected: the custom audiences go on `ooh-control-centre` only, not on `ooh-stage-check` (section 8 stands).
51. README rows: `FAIL ooh-stage-check enabled with no check running` → "run `install/77-check-stage-3.sh <tag>` once (it takes over the stale lock and disables the client on exit), then run 40 again"; `STOP: another check is running` → wait for it, or remove a stale lock only when its pid is gone (the script does this itself).
52. The worker's "Kafka consumer alive" = the consumer thread is running without a fatal error (not time since the last poll); Part A test.

53. `stage_check_token <audience>`: the argument is only a guard. The helper gets the normal client-credentials token (never sends an `audience` parameter) and checks that its `aud` contains `<audience>`; otherwise `STOP: stage-check token lacks audience <audience>`.
54. The Control Centre's own `People.Observe` sets `is_service_account` from the verified token by the same rule as 48; Part D test.
