# QUICK GUIDE

1. Type this in your harness terminal, in the plain shell. Claude runs this while Aziz watches. It prepares the consumer databases, private test settings and credential copies. No password is needed. Finish platform apply and realm sync first, as the root guide describes.

   ```bash
   cd ~/projects/worktrees/stage-4-part-b
   install/74-consumers-setup.sh
   ```

   Good result: `DONE`. Existing passwords are preserved; nothing is printed. After the merge use `cd ~/projects/worktrees/stage-4`; after acceptance use `cd ~/projects/open-office-harness`.

2. Do this in your PC browser after each first green image build. Make the three GitHub packages Public in their settings. Good result: each package says Public and pulls anonymously.

   [Audit writer](https://github.com/users/frozenfussion/packages/container/ooh-audit-writer/settings), [cost meter](https://github.com/users/frozenfussion/packages/container/ooh-cost-meter/settings), [safety watcher](https://github.com/users/frozenfussion/packages/container/ooh-safety-watcher/settings).

3. Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. It checks all three public images before applying any consumer manifests, then waits for the new revisions and database migrations. No password is needed. Deploy the Control Centre and Gateway first as the root guide describes.

   ```bash
   cd ~/projects/worktrees/stage-4-part-b
   install/75-consumers-deploy.sh "$(git rev-parse --short=12 HEAD)"
   ```

   Good result: three intended image names and `DONE`. Every image must have a green workflow for that tag. The deployment script makes no model calls. The running safety watcher makes classification calls for incoming messages; those can incur configured model charges.

4. Type this in your harness terminal, in the plain shell. The folder does not matter. It shows this consumer and its image. No password is needed.

   ```bash
   kubectl -n ooh-apps get pods -l app=cost-meter -o wide
   kubectl -n ooh-apps get deployment cost-meter -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   ```

   Good result: one Ready pod with the intended image. Requests are 50m CPU / 96Mi, limits 1 CPU / 512Mi. Actual use is checked after deployment.

5. Type this in your harness terminal, in the plain shell. The folder does not matter. It reads recent JSON logs without message text or credentials. No password is needed.

   ```bash
   kubectl -n ooh-apps logs deployment/cost-meter -c cost-meter --since=10m
   ```

   Good result: JSON lines without private content. For migration failures, read the migration logs with the next command.

   Type this in your harness terminal, in the plain shell. The folder does not matter. It reads migration logs. No password is needed.

   ```bash
   kubectl -n ooh-apps logs deployment/cost-meter -c migrate
   ```

   Good result: a JSON line saying migrations completed, or a fixed failure message without credentials.

6. Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It restarts this consumer. No password is needed.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/cost-meter
   kubectl -n ooh-apps rollout status deployment/cost-meter --timeout=600s
   ```

   Good result: rollout completed. After a reboot Kubernetes starts it automatically; allow five minutes, use step 4 and the root guide's stage check.

7. Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It stops this consumer without deleting data. No password is needed.

   ```bash
   kubectl -n ooh-apps scale deployment/cost-meter --replicas=0
   ```

   Good result: deployment scaled. Kafka retains queued work.

   Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It starts this consumer again. No password is needed.

   ```bash
   kubectl -n ooh-apps scale deployment/cost-meter --replicas=1
   ```

   Good result: deployment scaled; step 4 shows one Ready pod.

8. Type this in your harness terminal, in the plain shell. It runs the package checks with fake Kafka and model calls. No password is needed. Run setup first; never print the private settings.

   ```bash
   cd ~/projects/worktrees/stage-4-part-b/consumers/cost-meter
   set +x
   set -a
   source ~/.config/ooh/cost-meter-test.env
   set +a
   uv sync --frozen
   uv run ruff check
   uv run ruff format --check
   uv run pytest
   ```

   Good result: all checks pass. Database tests require only `costmeter_test` and run owner/app mutation checks inside rolled-back transactions. Missing private settings skip the database tests with a reason. The pinned TestClient emits a deprecation warning; no dependency is added for it.

9. Type this in your harness terminal, in the plain shell. It checks scripts and contracts without changing the cluster. No password is needed.

   ```bash
   cd ~/projects/worktrees/stage-4-part-b
   bash -n install/74-consumers-setup.sh install/75-consumers-deploy.sh
   shellcheck install/74-consumers-setup.sh install/75-consumers-deploy.sh
   uv run --project contracts/check pytest contracts/check/tests
   ```

   Good result: shell checks print no errors; every contract test passes. The merged root guide describes the full stage check; it makes a few short paid calls.

## Behavior

Consumes `audit.events` actions `model.call` and `model.classify` into append-only `model_costs` in `costmeter`; skips other actions. A model action without both `model` and `model_entry_id` is counted as handled without a cost row or dead letter, as the binding spec clarification requires. Owner migrations create grants and triggers rejecting UPDATE, DELETE and TRUNCATE for both owner and application roles. Only the Control Centre service account with audience `ooh-cost-meter` can read `/v1/costs?day=YYYY-MM-DD`: UTC total USD, calls, tokens and totals grouped by model title. Costs come from events, never recalculated from prompts or another service's database.

### Summary route date selection

`GET /v1/costs?day=YYYY-MM-DD` still selects that whole UTC day. Alternatively, send `from` and `to` together as ISO 8601 UTC timestamps (`Z` or a zero UTC offset). The range includes `from` and excludes `to`; it must be positive and no longer than 31 days. Neither parameter may be supplied alone, even with `day`. A complete range takes precedence over `day` if both forms are sent. Invalid or missing date selection returns HTTP 400 `invalid_input`. The same caller and audience checks apply to both forms.

The caller calculates display-zone boundaries and sends UTC instants. For the display day 11 November 2026 in Asia/Kuala_Lumpur, the internal request is `/v1/costs?from=2026-11-10T16:00:00Z&to=2026-11-11T16:00:00Z`. Response fields keep their existing types and shape; `day` is the UTC date of `from`, so this example returns `2026-11-10`. Zero offsets containing `+` must be URL-encoded in a query string. Example response:

```json
{"day":"2026-11-10","total_usd":0.000451,"calls":1,"tokens":826,"by_model":[{"model":"Fake entry","calls":1,"tokens":826,"cost_usd":0.000451}]}
```

Every package has its own code, lock file and Dockerfile. Schemas are bundled under `consumer/schemas`; tests compare every bundled schema with its contract. Kafka uses SASL_PLAINTEXT / SCRAM-SHA-512, group `cost-meter`, manual commit after handling and earliest reset. Invalid envelope or payload goes directly to `dlq.<topic>`; other failures get three retries after 1, 5 and 15 seconds. A failed DLQ delivery stops the consumer without committing the input. A non-fatal Kafka poll error logs its numeric code and polling continues. A permanently stopped consumer logs `consumer_stopped` and exits the process with code 1 so Kubernetes restarts it. Logs contain only fixed status messages and numeric codes. No real Kafka or provider is used in unit tests.

Outgoing event IDs are UUID v5 over the incoming ID plus outgoing type with the fixed contract namespace. A live process skips event IDs it already handled. The unique database key also drops duplicates after a restart. A dead letter keeps readable correlation/user IDs, otherwise a new UUID and `system`. The safety watcher's chat dead letters contain IDs only, including malformed payloads; never text or excerpts. Safety excerpts exist only in flagged approval messages, as Aziz explicitly approved.

`GET /health` requires no token and checks that the consumer task is running without fatal error. It also checks database connectivity. The service binds port 8080, has one replica, runs as 10001 with a read-only root and memory `/tmp`, and receives credentials through Kubernetes Secrets. There is no public ingress.

## Dependencies and verification

Versions match the stage's pinned stack: FastAPI 0.162.2, uvicorn 0.54.0, pydantic 2.14.3 (input/settings validation), httpx 0.28.1 (internal HTTP), PyJWT 2.15.1 and cryptography 50.0.2 (service identity), confluent-kafka 2.16.1 (Kafka with built-in librdkafka), jsonschema 4.26.0 (envelopes and payloads). psycopg[binary] 3.3.8 provides PostgreSQL without system packages. Tests use pytest 9.2.0 and respx 0.23.1; Ruff 0.17.4 checks formatting and lint. Every direct and transitive locked version was verified against official PyPI records on 11 November 2026; see the Part B report. Python 3.14.10 and uv 0.13.7 are reused from the Gateway image recipe. No system package is needed.

## STOP messages

| Message | Action |
|---|---|
| Usage / invalid image tag | Use the Quick Guide command; deployment needs one 12-character hexadecimal tag. |
| Invalid deployment value / missing tool | Ask the maintainer to correct settings or finish server setup. |
| Platform namespace missing / PostgreSQL not Ready / database resources not ready | Finish platform setup, inspect resource status and rerun setup. |
| Existing credentials unexpected / password format unexpected / invalid ClusterIP | Have the maintainer inspect the named resource privately; never print credentials. |
| `Keycloak client ooh-safety-watcher not found; run install/35-realm-sync.sh first` | Finish realm sync, then rerun consumer setup. |
| Cannot read client secret; check Keycloak bootstrap access | The Keycloak administration login failed; have the maintainer inspect bootstrap access privately. |
| Cannot contact Keycloak / client lookup or secret read failed / client secret missing or changed | Inspect pod readiness, realm/client permissions or the existing application copy privately, then rerun setup. |
| `KafkaUser <name> not ready; re-run 30` | Finish platform apply; setup waits at most 120 seconds, then can be rerun. |
| Kafka password changed | Have the maintainer reconcile the existing application Secret privately. |
| Database setup failed | Inspect PostgreSQL readiness and rerun setup; settings writes are atomic. |
| Image not built / not public | Wait for green image builds and make the named GitHub packages Public. |
| Registry unreachable / check failed / invalid token | Check registry availability and retry. |
| Required application secret missing | Run consumer setup. |
| Consumer not Ready / revision or migrations not verified / deployment failed | Inspect pod status and migration/application logs; rerun deployment. |
| HTTP 400 / 401 / 403 | Supply valid filters/day and an authorized Control Centre service token with this consumer's audience. |
| HTTP 503 / health down / consumer_stopped | Kubernetes restarts a stopped consumer automatically. If failure repeats, inspect database, Kafka and pod status and correct the cause. |

Builders do not execute setup, deployment or service-control commands. The merged stage run checks live readiness, actual memory use, paid provider calls and reboot recovery.

## Stage 4 tracing

`OTEL_EXPORTER_OTLP_ENDPOINT` empty or unset leaves tracing disabled: no provider or exporter is registered. Deployment settings select OTLP HTTP/protobuf, the internal Jaeger endpoint, service name and `parentbased_always_on` sampling. Health requests are excluded. A batch processor exports in the background with a five-second timeout. Export failures do not fail requests or Kafka processing.

Before export, each span is copied with only the attribute keys fixed in the Stage 4 spec section 8, no events or links, and an error status description containing only the error code (or no description). Request bodies, message text, query strings, provider addresses and exception messages are excluded. No database or global HTTP client instrumentation is installed. The HTTP instrumentation uses the stable HTTP attribute names.

Kafka consumers extract W3C `traceparent` and `tracestate` headers and create `process <topic>` consumer spans. Producers create `send <topic>` producer spans and inject UTF-8 byte headers before handing delivery to a thread. Audit events include the active valid trace ID; events created without one omit it. Invalid messages and exhausted retries mark consumer spans as errors without exporting exception details. Existing retries, duplicate handling and dead-letter behavior are retained.

OpenTelemetry API, SDK and OTLP HTTP exporter are pinned to 1.45.2; FastAPI and HTTPX instrumentation to 0.66b2. These and every newly locked transitive dependency were checked against official PyPI release records on 12 November 2026. They supply tracing, HTTP context propagation and export; Kafka propagation uses the API directly. Tests use the SDK's in-memory exporter and fake Kafka, with no Jaeger, Kafka broker or real model calls.
