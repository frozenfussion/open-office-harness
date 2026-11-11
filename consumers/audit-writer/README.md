# QUICK GUIDE

1. Type this in your harness terminal, in the plain shell. Claude runs this while Aziz watches. It prepares the consumer databases, private test settings and credential copies. No password is needed. Finish platform apply and realm sync first, as the root guide describes.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b
   install/74-consumers-setup.sh
   ```

   Good result: `DONE`. Existing passwords are preserved; nothing is printed. After the merge use `cd ~/projects/worktrees/stage-3`; after acceptance use `cd ~/projects/open-office-harness`.

2. Do this in your PC browser after each first green image build. Make the three GitHub packages Public in their settings. Good result: each package says Public and pulls anonymously.

   [Audit writer](https://github.com/users/frozenfussion/packages/container/ooh-audit-writer/settings), [cost meter](https://github.com/users/frozenfussion/packages/container/ooh-cost-meter/settings), [safety watcher](https://github.com/users/frozenfussion/packages/container/ooh-safety-watcher/settings).

3. Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. It checks all three public images before applying any consumer manifests, then waits for the new revisions and database migrations. No password is needed. Deploy the Control Centre and Gateway first as the root guide describes.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b
   install/75-consumers-deploy.sh "$(git rev-parse --short=12 HEAD)"
   ```

   Good result: three intended image names and `DONE`. Every image must have a green workflow for that tag. The deployment script makes no model calls. The running safety watcher makes classification calls for incoming messages; those can incur configured model charges.

4. Type this in your harness terminal, in the plain shell. The folder does not matter. It shows this consumer and its image. No password is needed.

   ```bash
   kubectl -n ooh-apps get pods -l app=audit-writer -o wide
   kubectl -n ooh-apps get deployment audit-writer -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   ```

   Good result: one Ready pod with the intended image. Requests are 50m CPU / 96Mi, limits 1 CPU / 512Mi. Actual use is checked after deployment.

5. Type this in your harness terminal, in the plain shell. The folder does not matter. It reads recent JSON logs without message text or credentials. No password is needed.

   ```bash
   kubectl -n ooh-apps logs deployment/audit-writer -c audit-writer --since=10m
   ```

   Good result: JSON lines without private content. For migration failures, read the migration logs with the next command.

   Type this in your harness terminal, in the plain shell. The folder does not matter. It reads migration logs. No password is needed.

   ```bash
   kubectl -n ooh-apps logs deployment/audit-writer -c migrate
   ```

   Good result: a JSON line saying migrations completed, or a fixed failure message without credentials.

6. Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It restarts this consumer. No password is needed.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/audit-writer
   kubectl -n ooh-apps rollout status deployment/audit-writer --timeout=600s
   ```

   Good result: rollout completed. After a reboot Kubernetes starts it automatically; allow five minutes, use step 4 and the root guide's stage check.

7. Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It stops this consumer without deleting data. No password is needed.

   ```bash
   kubectl -n ooh-apps scale deployment/audit-writer --replicas=0
   ```

   Good result: deployment scaled. Kafka retains queued work.

   Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It starts this consumer again. No password is needed.

   ```bash
   kubectl -n ooh-apps scale deployment/audit-writer --replicas=1
   ```

   Good result: deployment scaled; step 4 shows one Ready pod.

8. Type this in your harness terminal, in the plain shell. It runs the package checks with fake Kafka and model calls. No password is needed. Run setup first; never print the private settings.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b/consumers/audit-writer
   set +x
   set -a
   source ~/.config/ooh/audit-writer-test.env
   set +a
   uv run ruff check
   uv run ruff format --check
   uv run pytest
   ```

   Good result: all checks pass. Database tests require only `auditwriter_test` and run owner/app mutation checks inside rolled-back transactions. Missing private settings skip the database tests with a reason. The pinned TestClient emits a deprecation warning; no dependency is added for it.

9. Type this in your harness terminal, in the plain shell. It checks scripts and contracts without changing the cluster. No password is needed.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b
   bash -n install/74-consumers-setup.sh install/75-consumers-deploy.sh
   shellcheck install/74-consumers-setup.sh install/75-consumers-deploy.sh
   uv run --project contracts/check pytest contracts/check/tests
   ```

   Good result: shell checks print no errors; every contract test passes. The merged root guide describes the full stage check; it makes a few short paid calls.

## Behavior

Consumes `audit.events` into the append-only `trail` table in `auditwriter`. The owner runs migrations; the app role can SELECT/INSERT only. Database triggers reject UPDATE, DELETE and TRUNCATE for both roles. HTTP callers must be the Control Centre service account with audience `ooh-audit-writer`. `/v1/trail` accepts correlation ID, user ID, actor, action, before ID and limit (1–200, default 50); rows are newest first by event time and ID. `/v1/counts?day=YYYY-MM-DD` returns UTC counts by action and distinct real-user IDs, excluding `system` and the prefixes `title-`, `admin-test-`, `stage-check-`, `service-account-`.

Every package has its own code, lock file and Dockerfile. Schemas are bundled under `consumer/schemas`; tests compare every bundled schema with its contract. Kafka uses SASL_PLAINTEXT / SCRAM-SHA-512, group `audit-writer`, manual commit after handling and earliest reset. Invalid envelope or payload goes directly to `dlq.<topic>`; other failures get three retries after 1, 5 and 15 seconds. A failed DLQ delivery stops the consumer without committing the input. Logs contain only fixed status messages. No real Kafka or provider is used in unit tests.

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
| Cannot read client secret / client secret missing or changed | Inspect Keycloak and the safety watcher client privately before replacing the application copy. |
| `KafkaUser <name> not ready; re-run 30` | Finish platform apply; setup waits at most 120 seconds, then can be rerun. |
| Kafka password changed | Have the maintainer reconcile the existing application Secret privately. |
| Database setup failed | Inspect PostgreSQL readiness and rerun setup; settings writes are atomic. |
| Image not built / not public | Wait for green image builds and make the named GitHub packages Public. |
| Registry unreachable / check failed / invalid token | Check registry availability and retry. |
| Required application secret missing | Run consumer setup. |
| Consumer not Ready / revision or migrations not verified / deployment failed | Inspect pod status and migration/application logs; rerun deployment. |
| HTTP 400 / 401 / 403 | Supply valid filters/day and an authorized Control Centre service token with this consumer's audience. |
| HTTP 503 / health down / consumer_stopped | Inspect database, Kafka and pod status, correct the cause, then restart through the operator's shell tile. |

Builders do not execute setup, deployment or service-control commands. The merged stage run checks live readiness, actual memory use, paid provider calls and reboot recovery.
