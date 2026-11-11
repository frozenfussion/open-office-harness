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
   kubectl -n ooh-apps get pods -l app=safety-watcher -o wide
   kubectl -n ooh-apps get deployment safety-watcher -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
   ```

   Good result: one Ready pod with the intended image. Requests are 50m CPU / 96Mi, limits 1 CPU / 512Mi. Actual use is checked after deployment.

5. Type this in your harness terminal, in the plain shell. The folder does not matter. It reads recent JSON logs without message text or credentials. No password is needed.

   ```bash
   kubectl -n ooh-apps logs deployment/safety-watcher -c safety-watcher --since=10m
   ```

   Good result: JSON lines without private content. This package has no migration container.

6. Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It restarts this consumer. No password is needed.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/safety-watcher
   kubectl -n ooh-apps rollout status deployment/safety-watcher --timeout=600s
   ```

   Good result: rollout completed. After a reboot Kubernetes starts it automatically; allow five minutes, use step 4 and the root guide's stage check.

7. Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It stops this consumer without deleting data. No password is needed.

   ```bash
   kubectl -n ooh-apps scale deployment/safety-watcher --replicas=0
   ```

   Good result: deployment scaled. Kafka retains queued work.

   Type this in your harness terminal, in the plain shell. The folder does not matter. Claude runs it while Aziz watches. It starts this consumer again. No password is needed.

   ```bash
   kubectl -n ooh-apps scale deployment/safety-watcher --replicas=1
   ```

   Good result: deployment scaled; step 4 shows one Ready pod.

8. Type this in your harness terminal, in the plain shell. It runs the package checks with fake Kafka and model calls. No password is needed. No database setup is needed for these tests.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b/consumers/safety-watcher
   uv run ruff check
   uv run ruff format --check
   uv run pytest
   ```

   Good result: all checks pass. No paid calls or database are used. The pinned TestClient emits a deprecation warning; no dependency is added for it.

9. Type this in your harness terminal, in the plain shell. It checks scripts and contracts without changing the cluster. No password is needed.

   ```bash
   cd ~/projects/worktrees/stage-3-part-b
   bash -n install/74-consumers-setup.sh install/75-consumers-deploy.sh
   shellcheck install/74-consumers-setup.sh install/75-consumers-deploy.sh
   uv run --project contracts/check pytest contracts/check/tests
   ```

   Good result: shell checks print no errors; every contract test passes. The merged root guide describes the full stage check; it makes a few short paid calls.

## Behavior

Consumes `chat.messages` and completed `skill.results` summaries. It sends the envelope's user and correlation ID to the Gateway's classification route, using `SF_QUESTIONS` and `SF_THRESHOLD` (default 0.8). Every answer produces `safety.classify` audit scores; a score at or above the threshold also produces a `safety.flag` approval with up to 300 characters of excerpt. Failed skill results are skipped. Expected 404/no_model, 429 and 503 unavailable/budget/registry replies produce exactly `skipped_no_classifier`, `skipped_rate_limited` and `skipped_unavailable`, without retry or DLQ. Other failures follow the standard retry rule. It has no database and no HTTP data routes. Change questions/threshold in its ConfigMap and redeploy through the operator; there is no settings UI in this stage.

Every package has its own code, lock file and Dockerfile. Schemas are bundled under `consumer/schemas`; tests compare every bundled schema with its contract. Kafka uses SASL_PLAINTEXT / SCRAM-SHA-512, group `safety-watcher`, manual commit after handling and earliest reset. Invalid envelope or payload goes directly to `dlq.<topic>`; other failures get three retries after 1, 5 and 15 seconds. A failed DLQ delivery stops the consumer without committing the input. A non-fatal Kafka poll error logs its numeric code and polling continues. A permanently stopped consumer logs `consumer_stopped` and exits the process with code 1 so Kubernetes restarts it. Logs contain only fixed status messages and numeric codes. No real Kafka or provider is used in unit tests.

Outgoing event IDs are UUID v5 over the incoming ID plus outgoing type with the fixed contract namespace. A live process skips event IDs it already handled. After a restart, receivers deduplicate stable outgoing IDs; no processed-events table is added. A dead letter keeps readable correlation/user IDs, otherwise a new UUID and `system`. The safety watcher's chat dead letters contain IDs only, including malformed payloads; never text or excerpts. Safety excerpts exist only in flagged approval messages, as Aziz explicitly approved.

`GET /health` requires no token and checks that the consumer task is running without fatal error.  The service binds port 8080, has one replica, runs as 10001 with a read-only root and memory `/tmp`, and receives credentials through Kubernetes Secrets. There is no public ingress.

## Dependencies and verification

Versions match the stage's pinned stack: FastAPI 0.162.2, uvicorn 0.54.0, pydantic 2.14.3 (input/settings validation), httpx 0.28.1 (internal HTTP), PyJWT 2.15.1 and cryptography 50.0.2 (service identity), confluent-kafka 2.16.1 (Kafka with built-in librdkafka), jsonschema 4.26.0 (envelopes and payloads).  Tests use pytest 9.2.0 and respx 0.23.1; Ruff 0.17.4 checks formatting and lint. Every direct and transitive locked version was verified against official PyPI records on 11 November 2026; see the Part B report. Python 3.14.10 and uv 0.13.7 are reused from the Gateway image recipe. No system package is needed.

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
