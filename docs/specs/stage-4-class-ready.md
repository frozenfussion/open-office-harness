# Stage 4 phase 1 — Class-ready: tracing, failure demos with replay, Workspace fixes

Written 2026-11-12 by Claude (orchestrator). Read `00-GLOBAL-RULES.md` first; it applies in full.
**Base commit:** `main` right after this spec is merged. Before any Part starts, Claude tags that commit `stage-4-base` and pushes the tag from harness.
**Tags:** `class-start` when Aziz accepts phase 1 (the system the class starts from, and the fallback for the routing rebuild from `pre-routing`, D043). Phase 2 (AWS via Terraform, tag `eks-ready`) has its own spec, `stage-4b-aws.md`, written while phase 1 builds.

## 0. Aziz's words and decisions (Malaysia time)

- 07 Nov (planning chat, stack table): "Tracing: OpenTelemetry in every service. It covers the 'black box' part of your outline."
- 07 Nov 16:06–16:12: Kafka where it earns its place, including surviving a service being down and replay. COURSE-MAP Day 3 block 2: "Kill a worker mid-job: chat keeps working, job resumes; DLQ in Admin"; block 3: "One request traced end to end in Audit".
- 08 Nov (rehearsal plan v0.1, stage 5): "OpenTelemetry tracing, failure demos (kill a worker, DLQ retry), full README Quick Guide → class-start".
- 10 Nov 13:41 (D082, plan v0.2): Stage 4 = class-ready (tracing, failure demos; tag `class-start`) + AWS via Terraform (`eks-ready`).
- 11 Nov (Stage 3 spec section 4): dead letters are shown in Stage 3; "Replay is Stage 4 (failure demos)".
- 12 Nov 17:30: "yeah, go ahead and fix that" — the two Workspace issues carried from Stage 3 (D100): a saved chat link survives sign-in; words inside chat tables do not break mid-word.
- 12 Nov 17:31: "We need to get things done quickly." Phase 1 and phase 2 are specified separately so the builders start sooner.

## 1. Purpose

**One request, end to end.** Every service emits OpenTelemetry traces to Jaeger inside the cluster. A chat message or a Slides job becomes one trace: Harness API → Control Centre (rights) → Model Gateway → provider call, and across Kafka to the Slides worker, the audit writer, the cost meter and the safety watcher. Every audit row carries its `trace_id`; in the Admin Console's Audit screen a request opens its trace as a timeline. No new public address and no new sign-in: the Admin Console reads traces through the Control Centre, admin only.

**Failure demos, ready to show.** Worker down (chat keeps working, the job waits in Kafka and finishes when the worker returns); a duplicate message (one result, no second file); a dead letter and its **replay** from the Admin Console (the job that gave up completes after the cause is fixed). Each demo has a script that walks it step by step, and the README explains it.

**Two Workspace fixes.** A saved chat link opened while signed out opens that conversation after sign-in. Words inside chat tables never break in the middle.

## 2. Done when (all of these)

1. GitHub Actions builds all nine images for one commit, tagged with its first 12 characters; all pull without signing in.
2. On harness, from the merged `stage-4` worktree, every script in the README order (section 10) ends with `DONE` (Claude runs them in tile 3 where Aziz watches; none needs sudo). All pods in `ooh-apps` and the Jaeger pod in `ooh-platform` are Ready.
3. `install/78-check-stage-4.sh <tag>` prints `PASS` for every line and ends with `DONE` (section 9); `40`, `62`, `70` and `77 <tag>` still pass.
4. In the browser (Aziz): (a) Audit: a chat request and a Slides job each open a trace timeline showing the services named in section 1; (b) Failed messages: the dead letter made by the demo shows, **Replay** sends it again, and the job card turns Ready; (c) a saved conversation link opened in a signed-out window opens that conversation after sign-in; (d) a chat answer with a table shows whole words.
5. Each demo in `install/79-demo.sh` (worker-down, duplicate, dead-letter) runs to its end with `DONE` and says at each step what the audience should see.
6. After `sudo reboot`, `40`, `62`, `70`, `77` and `78` pass again without anyone touching the server (allow 5 minutes).
7. In a clean worktree of `stage-4`: every Part's checks pass; `uv run --project contracts/check pytest contracts/check/tests` passes; `bash -n` and `shellcheck` are clean for `install/*.sh install/lib/*.sh`; `kubeconform -strict` passes on `deploy/`.
8. `README.md` Quick Guide covers section 10 and the three demos; `docs/STATUS.md` says phase 1 is done and lists what was checked; `docs/ARCHITECTURE.md` and `contracts/identity.md` describe what was built.

## 3. Prerequisites

1. Tiles: 0 CODEX A, 1 CODEX B, 2 CLAUDE CODE, 3 SHELL, 4 CODEX C, 5 CODEX D (exist; Aziz attached).
2. The contract change in section 6.1 is in this spec's pull request.
3. No new databases. Part B adds one migration to the audit writer (owner role, init container, as Stage 3); Part D adds one Control Centre migration.
4. No Kafka and no Jaeger in unit tests: tracing is tested with the SDK's in-memory span exporter; Kafka headers with the existing fakes.

## 4. Decisions for this stage (fixed; versions checked 12 Nov 2026 on pypi.org, nuget.org and jaegertracing.io)

| Item | Decision | Why |
|---|---|---|
| Trace store and viewer | **Jaeger 2.23.0** (`cr.jaegertracing.io/jaegertracing/jaeger:2.23.0`), one pod in `ooh-platform`, OTLP receiver (HTTP 4318 only), **memory storage** (at most 20 000 traces, 15.8), query API on 16686 inside the cluster only; no Ingress | One binary, no database; traces are for demos and debugging, losing them on restart is acceptable (the audit trail is the permanent record) |
| Python SDK | `opentelemetry-api` and `opentelemetry-sdk` **1.45.2**, `opentelemetry-exporter-otlp-proto-http` **1.45.2**, `opentelemetry-instrumentation-fastapi` and `-httpx` **0.66b2** (all pinned in each lock file) | Newest; FastAPI and httpx spans automatic |
| Database spans | none in phase 1 (no psycopg or Npgsql instrumentation) | Keeps SQL text out of traces; the request path is what the demo needs |
| Kafka spans | **manual**: every producer injects the W3C `traceparent` (and `tracestate` when present) into the Kafka message **headers**; every consumer extracts it and starts a `CONSUMER` span `process <topic>` as a child; a producer send is a `PRODUCER` span `send <topic>`. No Kafka instrumentation package | The same small code in Python and C#; no beta package; the envelope stays unchanged |
| .NET | `OpenTelemetry.Extensions.Hosting`, `OpenTelemetry.Instrumentation.AspNetCore`, `OpenTelemetry.Instrumentation.Http`, `OpenTelemetry.Exporter.OpenTelemetryProtocol` **1.21.0** | Newest stable; ASP.NET and outgoing HTTP spans |
| Settings | standard OpenTelemetry environment variables in each ConfigMap: `OTEL_SERVICE_NAME` (= the Deployment name), `OTEL_EXPORTER_OTLP_PROTOCOL` `http/protobuf`, `OTEL_EXPORTER_OTLP_ENDPOINT` `http://jaeger.${PLATFORM_NAMESPACE}.svc:4318` (every service, the Control Centre included), `OTEL_TRACES_SAMPLER` `parentbased_always_on`. Empty or unset endpoint = no tracer provider registered (15.22), the service still runs | No code constants; tracing can never stop a service |
| What a span may carry | ids (user id, conversation id, job id, correlation id, model entry id), tier, purpose, skill, status codes, token counts. **Never** message text, prompts, thinking, file contents, keys, tokens, emails or names. HTTP spans: route template, not the full URL with query string | Global rules section 4 (logs) applies to spans too |
| Trace id in the audit trail | `audit.event` payload gains optional `trace_id` (32 lower-case hex); every producer of `audit.event` sets it from the current span; the audit writer stores it | One click from an audit row to its trace |
| Reading traces | Control Centre admin route `GET /api/admin/traces/{trace_id}` calls Jaeger's query API inside the cluster and returns a reduced shape (section 6.5); the Admin Console draws it | No new public address, no second sign-in |
| Dead-letter replay | Control Centre admin route `POST /api/admin/dead-letters/{id}/replay`: republishes the stored original message, unchanged (same envelope, same `event_id`, key = its `correlation_id`), to the source topic (`dlq.<topic>` → `<topic>`); records the replay in an append-only table and the audit; refuses `dlq.chat.messages` (ids only, nothing to replay) with 409 `not_replayable` | The consumer that failed never marked the `event_id` as handled, so the same id is processed now; no data is changed or deleted |
| Result after replay | the Harness accepts a `completed` `skill.result` for a job that is `failed` **with error code `worker_gave_up`** (and only that code): the job becomes `completed` and `job.completed` is sent; every other final status stays final | Lets a replayed job finish; a real failure or rejection is never overwritten |
| Worker result ids | the Slides worker's outgoing `event_id` = UUID v5 of the incoming `event_id` + `skill.result` + **the status** (`completed`/`failed`), so the failed result and a later completed result of the same request have different ids; a repeated completed request still gives the same id | Otherwise the Harness drops the completed result as a duplicate of the failed one |
| Demos | one script `install/79-demo.sh <worker-down|duplicate|dead-letter> <tag>` that runs one demo, prints each step in plain words ("Now ask for slides in the Workspace…"), waits for Enter where the presenter acts, and restores everything at the end (and on Ctrl+C) | One tool for the instructor; nothing left broken |
| Workspace saved link | the link is `/?conversation=<uuid>`; before the sign-in redirect the Workspace stores the `conversation` value (validated as a UUID) in `sessionStorage`; after sign-in it opens that conversation once and removes it (15.10) | The OIDC library's redirect loses the query today |
| Words in tables | inside rendered Markdown tables: `overflow-wrap: normal; word-break: normal`; the table sits in a horizontally scrollable wrapper (`overflow-x: auto`) so wide tables scroll instead of squeezing words; message text outside tables keeps `overflow-wrap: anywhere` | Long ids still wrap in text; words in tables stay whole |

## 5. Data

- **Audit writer**, new migration: `trail` gains `trace_id text null` (CHECK 32 lower-case hex) and an index on `trace_id`. Append-only rules unchanged.
- **Control Centre**, new migration: `dead_letter_replays` (append-only, trigger refuses UPDATE/DELETE/TRUNCATE): id uuid, dead_letter_id uuid (references `dead_letters`), replayed_by text, replayed_at timestamptz, target_topic text, outcome (`sent` | `failed`), error_code text null.

## 6. Interfaces

### 6.1 Contract change in this spec's pull request (spec author; the Parts read, never change it)
- `contracts/events/payloads/audit.event.schema.json`: optional `trace_id` (`^[0-9a-f]{32}$`); example updated.
- Kafka message headers `traceparent` / `tracestate` (W3C Trace Context) are allowed on every topic; they are not part of the envelope; `contracts/README.md` says so.

### 6.2 Harness API and Slides worker (Part A)
- Tracing as section 4 in both. Harness root span per HTTP request (FastAPI), child spans for Control Centre and Gateway calls (httpx, which also sends `traceparent`), Kafka PRODUCER spans on publish, CONSUMER spans on `skill.results` and `approvals.decided`. The Harness puts the current `trace_id` into every `audit.event` it publishes.
- Routing and title calls stay children of the chat request's span.
- Result after replay (section 4) and a test for it: `failed`/`worker_gave_up` + `completed` → `completed`; `failed`/other code + `completed` → unchanged; `rejected` + `completed` → unchanged.
- Worker: CONSUMER span from the request's headers; Gateway call as child (httpx); PRODUCER spans for `skill.result`, `audit.event`, `dlq.entry`; result ids as section 4 (test: failed then completed for the same request → two different ids; completed twice → same id).
- Tests: spans and parent links with the in-memory exporter; `traceparent` written to and read from Kafka headers; no message text in any span attribute; tracing off when the endpoint is unset.

### 6.3 Model Gateway and read-only consumers (Part B)
- Tracing as section 4. Gateway: server span per call, a child span `provider <connection type>` around each provider attempt (attributes: entry id, attempt number, status, tokens; never the body), classify likewise. `trace_id` in every `audit.event` it publishes.
- Audit writer, cost meter, safety watcher: CONSUMER spans from the incoming headers; the safety watcher's classify call (httpx) and its `approval.requested` and `audit.event` publishes carry the context on.
- Audit writer: stores `trace_id` (migration, section 5); `GET /v1/trail` returns `trace_id` per row and accepts the filter `trace_id=`.
- Tests: as Part A for each package; the audit writer stores and filters `trace_id`; an event without `trace_id` is still stored.

### 6.4 Platform, demos, check, Workspace (Part C)
- `deploy/platform/tracing/`: Deployment `jaeger` (1 replica, non-root, read-only root filesystem where the image allows, requests 100m/256Mi, limits 500m/1Gi, memory storage capped as section 4), Service `jaeger` (4318, 16686), its config file in a ConfigMap (contents: 15.9 and 15.28). `30-platform-apply.sh` applies it and waits for Ready; `40-check-platform.sh` adds one line: Jaeger Ready and its query API answers inside the cluster.
- KafkaUser `control-centre`: Write added to the existing `approvals.requested` entry; new Write + Describe entries for `skill.requests.slides` and `skill.results` (it already writes `approvals.decided` and `audit.events`; 15.15); `contracts/identity.md` table updated; `77` item 3 keeps passing (it compares with the table).
- `install/79-demo.sh` (section 4), three demos:
  - **worker-down:** scale `slides-worker` to 0 → presenter asks for slides (chat answers, card Queued) → script shows "slides-worker pods: 0" → scale back to the recorded count → card turns Ready (15.2, 15.20).
  - **duplicate:** publishes one `skill.requested` twice with the same `event_id` (check principal, as `77` item 5) → shows one result id and the file's unchanged modification time.
  - **dead-letter:** the order in 15.1 (worker to 0 → presenter asks for slides → Gateway to 0 → worker back → it gives up, card Failed → Gateway back → **Replay** → card Ready); `--auto` as 15.27. Restores both Deployments on any exit (15.20). Warns before starting that chat is unavailable while the Gateway is down.
  Each demo uses the shared check-client helper (`install/lib/stage-check.sh`) for admin calls and Kafka check pods, never prints a secret, and ends with `DONE`.
- `install/78-check-stage-4.sh <tag>` (section 9).
- Workspace: saved link and table fixes (section 4), with tests.
- `README.md`, `docs/ARCHITECTURE.md`, `contracts/identity.md`.

### 6.5 Control Centre and Admin Console (Part D)
- Tracing (.NET, section 4): ASP.NET server spans, outgoing HTTP spans, Kafka PRODUCER spans from the outbox publisher and CONSUMER spans for `approvals.requested` and the `dlq.*` topics with `traceparent` from the headers (the outbox stores the `traceparent` with the row when it is written, so the publish continues the request's trace). `trace_id` in every `audit.event` it publishes.
- `GET /api/admin/traces/{trace_id}` (admin; 32 hex, else 400): calls `{CC_JAEGER_QUERY_URL}/api/v3/traces/{trace_id}` (setting, no address in code) and answers `{trace_id, spans: [{span_id, parent_span_id, service, name, kind, start, duration_ms, status, attributes}]}` sorted by start; attributes only from an allow-list (the ids, tier, purpose, skill, status codes, tokens of section 4); 404 `trace_not_found`; 503 `tracing_unavailable` when Jaeger does not answer (the screen says so; never a failure of the rest of the Audit screen).
- `GET /api/admin/trail` passes `trace_id` through (audit writer field) and accepts the `trace_id` filter.
- `POST /api/admin/dead-letters/{id}/replay` (admin) as section 4: 202 `{replay_id, target_topic, outcome}`; 404 unknown id; 409 `not_replayable` for `dlq.chat.messages` or an original message that is not valid JSON; 503 `kafka_unavailable` (a `failed` replay row is written). Audit action `dead_letter.replayed` (ids and topic only). `GET /api/admin/dead-letters` rows add `replay_count`, `last_replayed_at`, `replayable`.
- Admin Console:
  - **Failed messages** screen (nav item after Audit): the dead letters, newest first, filter by topic; detail pane with topic, error, time, request ID (copy) and the original message (admin only, pretty-printed, read-only); **Replay** (disabled with the reason when not replayable) → confirm → result line; replay history.
  - **Audit**: each row with a `trace_id` gets **Trace**; it opens a timeline: one row per span, indented by parent, bar by start and duration, service name, status (OK/error chip), allow-listed attributes on click; "Tracing is unavailable" or "This trace has expired" messages.
  - The Overview's `dead_letter` attention item links to Failed messages.
- `deploy/apps/control-centre/configmap.yaml`: `CC_JAEGER_QUERY_URL` `http://jaeger.${PLATFORM_NAMESPACE}.svc:16686` and the OpenTelemetry settings.

## 7. Parts

Four Codex windows at the same time, each in its own worktree from `stage-4-base`, Full Access. **No Part changes a file another Part lists.** Nobody changes the files in section 11.

### Part A — Harness API + Slides worker (branch `stage-4-part-a`, Codex A, tile 0)
```
services/harness-api/**
workers/slides/**
deploy/apps/harness-api/*.yaml                   (OpenTelemetry settings)
deploy/apps/slides-worker/*.yaml                 (OpenTelemetry settings)
contracts/http/harness-api.openapi.yaml, contracts/examples/http/harness-api.*, contracts/examples/index.harness-api.json   (only if a shape changes)
```

### Part B — Model Gateway + read-only consumers (branch `stage-4-part-b`, Codex B, tile 1)
```
services/model-gateway/**
consumers/audit-writer/**                        (trace_id migration, route field and filter)
consumers/cost-meter/**
consumers/safety-watcher/**
deploy/apps/model-gateway/*.yaml
deploy/apps/audit-writer/*.yaml
deploy/apps/cost-meter/*.yaml
deploy/apps/safety-watcher/*.yaml
contracts/http/model-gateway.openapi.yaml, contracts/examples/http/model-gateway.*, contracts/examples/index.model-gateway.json   (only if a shape changes)
```

### Part C — Platform, demos, check, Workspace (branch `stage-4-part-c`, Codex C, tile 4)
```
deploy/platform/tracing/**
deploy/platform/kafka/users/control-centre.yaml
install/30-platform-apply.sh
install/40-check-platform.sh
install/78-check-stage-4.sh
install/79-demo.sh
apps/workspace/**
contracts/identity.md
docs/ARCHITECTURE.md
README.md
```

### Part D — Control Centre + Admin Console (branch `stage-4-part-d`, Codex D, tile 5)
```
services/control-centre/**                       (tracing, replay, trace proxy, migration, tests, README)
contracts/http/control-centre.openapi.yaml
contracts/examples/http/control-centre.*
contracts/examples/index.control-centre.json
apps/admin-console/**                            (Failed messages, Trace view, Overview link)
deploy/apps/control-centre/*.yaml
install/61-control-centre-deploy.sh              (only if it must change)
install/69-admin-console-deploy.sh               (only if it must change)
```

**Checks for every Part:** as Stage 3 for each package it owns (Python: `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest`; .NET: format, build with warnings as errors, test, no pending model changes; Angular: `npm ci`, `npx ng build`, `npx ng test --watch=false`); contract check; `bash -n` + `shellcheck -x` for its scripts; `kubeconform -strict` for its manifests. Each builder checks every new package version on its official page on the day and reports it.

### Merge, deploy, check
Claude makes `stage-4` from `stage-4-base` in `~/projects/worktrees/stage-4`, merges A–D and the spec-rows branch, runs every check of section 2 item 7 on a clean worktree, writes the `docs/STATUS.md` phase 1 section, pushes `stage-4` (after Aziz's yes), runs all nine image workflows for the merge commit, deploys in the README order and runs the checks.

## 8. Fixed names between the Parts

| What | Value |
|---|---|
| Jaeger | Deployment and Service `jaeger` in `ooh-platform`; Service ports 4318 (OTLP HTTP), 16686 (query); probes on 13133 `/status` |
| Settings | `OTEL_SERVICE_NAME` = Deployment name (`harness-api`, `slides-worker`, `model-gateway`, `audit-writer`, `cost-meter`, `safety-watcher`, `control-centre`); `OTEL_EXPORTER_OTLP_ENDPOINT`; `OTEL_TRACES_SAMPLER`; `CC_JAEGER_QUERY_URL` |
| Kafka headers | `traceparent`, `tracestate` (bytes, UTF-8) |
| Span names | HTTP: instrumentation default (method + route template); Kafka: `send <topic>`, `process <topic>`; Gateway: `provider <connection type>`, `classify` |
| Audit | payload field `trace_id`; trail column `trace_id`; route filter `trace_id=` |
| Replay | route `POST /api/admin/dead-letters/{id}/replay`; audit action `dead_letter.replayed`; error codes `not_replayable`, `kafka_unavailable`; table `dead_letter_replays` |
| Result after replay | only error code `worker_gave_up` may be followed by `completed` |
| Scripts | `78-check-stage-4.sh <tag>`; `79-demo.sh <worker-down\|duplicate\|dead-letter> <tag> [--auto]`; `79-demo.sh restore` (no tag, no check client) |
| Span attribute keys (the only ones exported; every filter and the Control Centre allow-list use exactly these) | `ooh.user_id`, `ooh.conversation_id`, `ooh.job_id`, `ooh.correlation_id`, `ooh.model_entry_id`, `ooh.tier`, `ooh.purpose`, `ooh.skill`, `ooh.status`, `ooh.error_code`, `ooh.attempt`, `ooh.tokens`, `ooh.connection_type`, `http.request.method`, `http.route`, `http.response.status_code`, `server.port`, `messaging.destination.name`, `messaging.operation.type` |

## 9. `install/78-check-stage-4.sh <tag>` (Part C), one `PASS`/`FAIL` line each, then `DONE`

Uses `install/lib/stage-check.sh` as `77` does (lock, temporary check client, tokens never printed). Kafka through short-lived check pods.
1. Every Deployment in `ooh-apps` runs `:<tag>` and is Ready; Jaeger is Ready.
2. A non-streamed chat call through the Harness as the check user (tier 1) → its audit rows carry one `trace_id`; within 60 s `GET /api/admin/traces/{trace_id}` shows spans from `harness-api`, `control-centre` and `model-gateway`, with the Gateway span a descendant of the Harness span.
3. A Slides job published as in `77` item 4 with a `traceparent` header → the trace holds spans from `slides-worker`, `model-gateway` and `audit-writer` under that trace id.
4. No span attribute in items 2–3 contains the check's question text or the slide topic (the check sends a unique marker word and searches the raw Jaeger answer for it, inside the check pod; prints only PASS/FAIL).
5. Replay: with the Gateway scaled to 0 (restored on every exit), a Slides request → within 120 s a `worker_gave_up` result and a dead letter for it; Gateway back and Ready; `POST …/replay` → 202 `sent`; within 180 s a `completed` result for the same correlation id and the job's file exists; a second replay of a `dlq.chat.messages` row (if any; else the check publishes none and prints `SKIP`) → 409.
6. `GET /api/admin/dead-letters` shows `replay_count` ≥ 1 for that dead letter; the audit trail holds `dead_letter.replayed`.
7. `ooh-stage-check` disabled again (as `77` item 13).
Each run makes a few short paid calls and briefly stops the Gateway (the README says so; never run it during a class).

## 10. README Quick Guide additions (Part C)
1. Stage 4 order: 30 → 61 → 65 → 67 → 73 → 75 → 68 → 69 → 40 → 62 → 70 → 77 → 78 (no new setup scripts).
2. Opening a trace from Audit; what "Tracing is unavailable" and "This trace has expired" mean (Jaeger keeps traces in memory; a restart clears them; the audit trail stays).
3. The three demos: when to use each, the exact command, what the audience sees at each step, how to stop one safely.
4. Replaying a dead letter by hand; which ones cannot be replayed and why.
5. Every new `STOP:` and `FAIL` and what to do.

## 11. Files that already exist (spec author's; Codex does not change them)
`AGENTS.md`, `CLAUDE.md`, `LICENSE`, `docs/specs/*`, `docs/plan/*`, `docs/images/*`, `docs/design/*`, `docs/routing/*`, `apps/design-system/*`, `contracts/check/*`, `contracts/events/*`, `contracts/skills/*`, `contracts/storage.md`, `contracts/README.md`, `install/01-server-setup.sh`, `install/lib/stage-check.sh`, and every earlier file not listed in a Part. If a Part believes one must change, it stops and asks with the reason.

## 12. Pre-mortem

| Step | Failure | How it shows | Action |
|---|---|---|---|
| Tracing | the exporter blocks or fails | slow requests; export errors in logs | batch span processor, export timeout 5 s, never on the request path; tracing off when the endpoint is unset; item 2 |
| Trace across Kafka | `traceparent` lost by one producer or consumer | the worker's spans in a separate trace | item 3 checks one trace id across the hop |
| Personal data | message text in a span attribute or a SQL statement | — | allow-lists, no database instrumentation, item 4 |
| Jaeger memory | many traces | Jaeger restarts (OOMKilled) | trace cap, 1 Gi limit; losing traces is acceptable |
| Replay | the consumer still fails | a new dead letter | the replay row and audit show it; replay is repeatable |
| Replay of a finished job | duplicate side effects | — | the worker reuses a finished file; the Harness only revives `worker_gave_up` |
| Demo leaves the Gateway or worker down | chat or slides stop | — | `trap` restores on every exit; `40`/`77` show it |
| Outbox and traces | the outbox publishes later, outside the request | a separate trace | the outbox row keeps the `traceparent` |

## 13. Out of scope for phase 1
AWS, Terraform, EKS (phase 2 spec); metrics and logs pipelines; database spans; browser-side tracing; a public Jaeger address; uploads; new skills; Helm.

## 14. Changes agreed during the build — these override the sections above

| # | Change | Who / when |
|---|---|---|
| 1 | Spec review by Claude Code (25 findings): every finding resolved in section 15, which is binding and overrides any line above that disagrees | Spec author, 12 Nov |
| 2 | Spec re-review (findings 1, 9, 13 partly open; 26–33 new): resolved in section 15 "Re-review additions"; body lines corrected in place to match section 15 | Spec author, 12 Nov |

## 15. Decisions from the spec review (binding; override anything above that disagrees)

Review by Claude Code, 12 Nov 2026 (`reviews/stage-4-spec-review` in the course folder, 25 findings). Numbers = review findings.

**Demos and check**
1. Dead-letter demo, in this order: scale `slides-worker` to 0 → the presenter asks for slides in the Workspace (card Queued) → scale `model-gateway` to 0 → scale `slides-worker` back to its recorded count (it retries, gives up, publishes `worker_gave_up` and the dead letter; the card shows Failed) → scale the Gateway back and wait for Ready → the presenter clicks **Replay** (or `--auto` replays the dead letter whose `correlation_id` is the newest job of the check user) → the card turns Ready. `78` item 5 keeps the direct Kafka publish and checks the Kafka and Control Centre part only; the Harness revive rule is proved by Part A's tests and browser test 4(b).
2. Worker-down demo: no consumer-lag step. It shows "slides-worker pods: 0" and the Queued card, then the card turning Ready after the worker returns. No ACL change for `ooh-stage-check`; `77` stays untouched.
17. `78` item 2: one chat message through the Harness with the stream read to its end; the correlation id is the user message id from the stream.
18. `78` item 3 sends `traceparent` `00-<random 32 hex>-<random 16 hex>-01`.
19. `78` item 5, last clause: replay of a dead letter whose original message is not JSON (`77` item 6 makes one; else the check publishes `not json` itself) → 409 `not_replayable`. `dlq.chat.messages` → 409 is a Part D unit test.
20. `79-demo.sh` traps `EXIT INT TERM HUP`, records each Deployment's replica count before scaling and restores that count; `79-demo.sh restore` puts `model-gateway` and `slides-worker` back to their manifest counts (README row); `40` prints `FAIL model-gateway scaled to 0 (run install/79-demo.sh restore)` (and the same for `slides-worker`) when either has 0 desired replicas.

**What spans may carry (replaces the section 4 row where it disagrees)**
3. (a) Every service installs one span processor that drops every attribute not on the allow-list (section 4 ids, tier, purpose, skill, status codes, tokens, plus `http.request.method`, `http.route`, `http.response.status_code`, `server.port`) before export. (b) No `record_exception` and no exception events anywhere; an error sets the span status to error with the error code only (FastAPI instrumentation configured accordingly). (c) The Gateway's provider HTTP client is **not** auto-instrumented; the manual `provider <connection type>` span is the only span for a provider call; only the Harness, Gateway, worker, safety watcher and Control Centre clients to our own services and Keycloak are instrumented. `78` item 4 also checks the raw Jaeger answer has no `url.full`, no `exception` event, no `user_agent.original`, no `client.address`.
13. The two public APIs (Harness API, Control Centre) ignore incoming `traceparent`/`tracestate` on HTTP and always start a new root span; internal services keep `parentbased_always_on`. Test in Parts A and D.
22. When `OTEL_EXPORTER_OTLP_ENDPOINT` is empty or unset, no tracer provider or exporter is registered (the no-op API stays); test in every package. In .NET the manual Kafka `ActivitySource` is registered with `AddSource` (test).
12. Producers omit `trace_id` when the span context is not valid. The contract (this pull request) refuses `00000000000000000000000000000000`; the audit writer's CHECK does too; test with tracing off.
21. One OTLP protocol: `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` and `http://jaeger.${PLATFORM_NAMESPACE}.svc:4318` for every service, the Control Centre included. Jaeger's Service exposes 4318 and 16686 only (and 13133 for probes, not in the Service).

**Schemas, ids and replay**
4. Every Part replaces its packages' copies of `audit.event.schema.json` (and of the envelope where copied) with the contract file byte for byte, and adds a test comparing them (as the audit writer has): Part A `services/harness-api/harness_api/event_schemas/`, `workers/slides/slides_worker/schemas/`; Part B `consumers/*/consumer/schemas/` and any copy in the Gateway; Part D `services/control-centre/ControlCentre/Platform/Schemas/`. Part B adds a test that an `audit.event` with `trace_id` is accepted by the audit writer and the cost meter.
25. At `stage-4-base` the audit writer's schema-copy test fails until Part B syncs its copy; Part B does that first. Other Parts do not stop for it.
5. The worker's `audit.event` id also includes the status: `uuid5(incoming event_id + "audit.event" + status)`; Part A test: failed then completed for one request → two audit ids.
6. Part D removes the `ProcessedEvents` insert from the dead-letter path of the Control Centre's approval consumer, so a replayed `approvals.requested` is processed; test: a dead-lettered approval, once replayed, creates the approval.
14. The replayed message carries the `traceparent` of the replay request (a `send <topic>` PRODUCER span under the admin's HTTP span); the `dead_letter.replayed` audit row carries that `trace_id`. Replay publishes directly with the producer (not through the outbox), waiting for the delivery result, so 202 `sent` / 503 `kafka_unavailable` are true.
15. KafkaUser `control-centre`: add `Write` to the existing `approvals.requested` entry (operations Write, Read, Describe); one new entry each, Write + Describe, for `skill.requests.slides` and `skill.results`; `audit.events` already has Write. One entry per topic, so `77` item 3 still passes. (Corrects 6.4.)
16. Part C: in the Workspace a `job.completed` event or a reloaded `completed` row replaces a `failed` row whose error code is `worker_gave_up`; test.
24. README replay section: replaying to `skill.results` or `audit.events` also re-delivers to consumers that already handled it; they drop it, except that the safety watcher may classify once more after a restart (one paid call; a duplicate flag is dropped by `event_id`).

**Tracing internals**
7. Harness Kafka publishing: the PRODUCER span is started and `traceparent` injected into the headers in the async `publish()` before the hand-off to the thread pool; test through the real `KafkaBus.publish` path with a fake producer (header trace id = caller's).
8. Health checks are not traced: `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=health` in every Python ConfigMap; the Control Centre's ASP.NET instrumentation filters `/health` and `/api/admin/health`, and its health poller's outgoing calls are not traced. Jaeger `max_traces` 20 000 with the `memory_limiter` processor; `40` prints `INFO jaeger restarted <n> times` when its restart count is above 0.
9. Jaeger config (ConfigMap, Part C): receivers `otlp` only with `http.endpoint: 0.0.0.0:4318`; extensions `jaeger_storage` (memory, `max_traces: 20000`), `jaeger_query` (`http.endpoint: 0.0.0.0:16686`, no AI or MCP block, no remote or adaptive sampling) and `healthcheckv2` on 13133 for readiness and liveness; processors `memory_limiter`, `batch`. `40`'s Jaeger line sends one OTLP/HTTP span from a check pod to `jaeger:4318` and reads it back from 16686.
10. Workspace saved link: the link is `/?conversation=<uuid>`. Before the sign-in redirect the Workspace stores the `conversation` query value (validated as a UUID) in `sessionStorage`; after sign-in it opens that conversation once and removes the value; any other value is ignored; test with a non-UUID value.
11. Section 5 addition: in the same Control Centre migration `outbox` gains `traceparent text null` and `tracestate text null`; Part D test: an audit row written inside a request is published with that request's trace id.
23. Jaeger's answer to `GET /api/v3/traces/{id}` is OTLP JSON wrapped as `{"result": {"resourceSpans": [...]}}`: `traceId`/`spanId`/`parentSpanId` as hex, `kind` as an enum, start and end as nanosecond strings, service name in `resource.attributes["service.name"]`; 404 when the trace is unknown. Part D builds its parser and fixture from Jaeger 2.23.0's own documentation or a captured answer, and reports which.

**Re-review additions (binding; numbers = re-review findings)**
26. Replaces 15.3(a)/(b) on how: **Python**: a filtering wrapper around the OTLP span exporter that copies each span with only the section 8 attribute keys and no events, passed to the real exporter inside a `BatchSpanProcessor`. **.NET**: a `BaseProcessor<Activity>` that in `OnEnd` removes tags not in the section 8 list and clears events. No span events are exported anywhere. Test in every package: an unhandled route error exports a span with status error, no events and no attribute outside the list.
27. `--auto` waits for, and replays, the newest dead letter on `dlq.skill.requests.slides` with error code `worker_gave_up` received after the script scaled the Gateway to 0 (`GET /api/admin/dead-letters?topic=dlq.skill.requests.slides`, compared by `received_at`); none within 120 s → `STOP: no dead letter arrived; is the worker running?`.
28. Jaeger config additions: `healthcheckv2: {use_v2: true, http: {endpoint: 0.0.0.0:13133, status: {enabled: true, path: /status}}}`, readiness and liveness `httpGet /status` on 13133; `memory_limiter: {check_interval: 1s, limit_mib: 800, spike_limit_mib: 150}` first in the processor list; no `telemetry` or `pprof` blocks. The builder confirms each key against Jaeger 2.23.0's own example configs and reports.
29. Replaces 15.13: incoming `traceparent`/`tracestate` is dropped only on requests that came through the ingress, recognised by the `X-Forwarded-For` header Traefik adds. In the Harness (Python: ASGI middleware outside the OpenTelemetry middleware that removes the two headers from the scope when `X-Forwarded-For` is present) and the Control Centre (.NET: the same rule in a propagator wrapper or middleware ahead of the ASP.NET instrumentation). In-cluster calls (the Harness calling the Control Centre's rights routes on 8080) keep their trace. Tests: Part D, a request with `traceparent` and no `X-Forwarded-For` continues that trace; Parts A and D, a request with both gets a new trace.
30. Span attribute keys are fixed in section 8; Parts A and B write only those keys, every filter and the Control Centre trace route allow exactly those.
31. Body lines in sections 4, 6.4 and 8 corrected in place to agree with section 15.
32. The Gateway keeps two HTTP clients: one for Keycloak and the Control Centre, instrumented with `HTTPXClientInstrumentor.instrument_client`, and one uninstrumented client for providers. No package calls the global `HTTPXClientInstrumentor().instrument()`; each instruments its own clients with `instrument_client`. Part B test: a provider call produces only the `provider <connection type>` span.
33. Section 8 Scripts row gives both forms of `79-demo.sh`; `restore` takes no tag and needs no check client.
