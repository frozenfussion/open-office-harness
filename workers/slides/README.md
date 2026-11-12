# QUICK GUIDE

1. Set up the worker's secrets after platform apply and realm sync.

   Type this in your harness terminal, in the plain shell. Claude runs it while
   Aziz watches. No password is needed. This copies the existing Kafka and
   sign-in credentials without printing them.

   ```bash
   cd ~/projects/worktrees/stage-4
   bash install/72-slides-worker-setup.sh
   ```

   Good result: `DONE`. Existing credentials must match; they are never replaced.

2. Run the local checks.

   Type this in your harness terminal, in the plain shell. No password is
   needed. This checks the worker with fake Kafka and a fake model; no paid
   model calls are made.

   ```bash
   cd ~/projects/worktrees/stage-4-part-a/workers/slides
   uv sync --frozen
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest
   ```

   Good result: both Ruff checks pass and all tests pass. At the merge, use
   `cd ~/projects/worktrees/stage-4/workers/slides` instead.

3. Deploy after the Slides worker image workflow is green and Aziz has made
   the `ooh-slides-worker` GitHub package public. The merged worktree must
   include Part C's shared check-client helper and Part D's Control Centre.

   Type this in your harness terminal, in the plain shell. Claude runs it while
   Aziz watches. No password is needed. This deploys the worker and registers
   its Slides manifest; it makes no model calls.

   ```bash
   cd ~/projects/worktrees/stage-4
   bash install/73-slides-worker-deploy.sh "$(git rev-parse --short=12 HEAD)"
   ```

   Good result: the expected image, `PASS ooh-stage-check disabled`, then
   `Slides manifest registered` and `DONE`. The check client is enabled only
   around manifest registration and its credentials are never printed.
   Aziz then grants himself Slides in People & rights.

4. Check status and the image.

   Type this in your harness terminal, in the plain shell. The folder doesn't
   matter for this command. This shows one ready replica and the image tag.

   ```bash
   kubectl -n ooh-apps get deployment slides-worker -o wide
   ```

5. Read recent logs.

   Type this in your harness terminal, in the plain shell. The folder doesn't
   matter for this command. This reads JSON service logs without file contents
   or credentials.

   ```bash
   kubectl -n ooh-apps logs deployment/slides-worker --tail=100
   ```

6. Restart when needed.

   Type this in your harness terminal, in the plain shell. Claude runs it while
   Aziz watches. The folder doesn't matter for this command. This restarts the
   worker; the current job is allowed time to finish.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/slides-worker
   ```

   Repeat the status step until one replica is ready.

7. Stop when needed.

   Type this in your harness terminal, in the plain shell. Claude runs it while
   Aziz watches. The folder doesn't matter for this command. This stops the
   worker; queued jobs remain in Kafka and files remain on the volume.

   ```bash
   kubectl -n ooh-apps scale deployment/slides-worker --replicas=0
   ```

8. Start again.

   Type this in your harness terminal, in the plain shell. Claude runs it while
   Aziz watches. The folder doesn't matter for this command. This resumes work
   from Kafka; repeat the status step until one replica is ready.

   ```bash
   kubectl -n ooh-apps scale deployment/slides-worker --replicas=1
   ```

9. After reboot, allow five minutes, then check status. Kubernetes starts the
   worker automatically if it had one replica before the reboot.

   Type this in your harness terminal, in the plain shell. Claude runs it while
   Aziz watches. No password is needed. This checks the complete stage and
   makes a few short paid model calls.

   ```bash
   cd ~/projects/worktrees/stage-4
   bash install/77-check-stage-3.sh "$(git rev-parse --short=12 HEAD)"
   ```

   Good result: all PASS lines and `DONE`. Aziz then asks for a presentation in
   the Workspace and downloads the Ready job to open it in PowerPoint.

## STOP messages

Fix the named problem, then repeat the same script. No script needs sudo.

| STOP text | Action |
|---|---|
| invalid deployment value / usage / missing tool | Correct the named value or argument, or finish server setup. |
| KafkaUser slides-worker not ready; re-run 30 | Run platform apply, wait for Strimzi, then repeat setup. |
| Kafka password changed in Strimzi / client secret changed | Ask the maintainer to inspect credentials privately before replacing anything. |
| could not read Slides worker client secret | Check Keycloak readiness and bootstrap access. |
| setup failed | Check platform readiness, then repeat setup. |
| image not built yet | Wait for the workflow or run it on demand for this commit. |
| image not found or not public | Check the workflow; Aziz makes the GitHub package public. |
| registry is unreachable / registry check failed / invalid token | Check registry availability, then retry. |
| required application secret missing | Run worker setup. |
| configuration hash could not be made | Check sha256sum and retry. |
| new revision is not Ready / current revision could not be verified / deployment failed | Inspect pod status, image visibility, files permissions and logs; then retry. |
| stage-check helper missing | Use the merged Stage 3 worktree. |
| another check is running | Wait; a stale lock is taken over only after its pid is gone. |
| could not start the stage check / obtain a token | Read the helper's STOP line and inspect Keycloak. |
| stage-check token lacks audience | Run realm sync and inspect the client audience mappers. |
| manifest read/save failed | Inspect Control Centre readiness and its HTTP status; retry. |
| stage-check client could not be disabled | Inspect Keycloak, then rerun deployment to disable it safely. |

## Worker and files

The worker consumes `skill.requests.slides`, group `slides-worker`, with
SCRAM-SHA-512 and explicit commits after handling. Invalid envelope or payload
schema goes straight to `dlq.skill.requests.slides`. Invalid Slides input and
unknown skills return a failed `skill.result`. Other failures get three retries
(after 1, 5 and 15 seconds); exhaustion publishes a dead letter and a failed
result so the person is told. Outgoing ids are UUID v5 from incoming id plus
outgoing type and result status (for results and audit), using the fixed namespace.

The Gateway supplies slide text as strict JSON. One correction call is allowed
for a bad shape. Each Gateway call keeps its own time limit; there is no shared
attempt deadline. The Kafka poll interval is 7,400,000 ms (binding spec section
14 row 7), covering four attempts of two 910-second calls plus retry waits and
margin. Health means the consumer thread is alive without a fatal error, even
while a model is taking time. Non-fatal Kafka errors keep polling. An unexpected
consumer-thread stop logs `consumer_stopped` and ends the process with exit 1
so Kubernetes restarts it. Normal shutdown finishes without a forced exit. It also rewrites only
`/files/outputs/slides/.health` to prove the volume is writable.

The worker makes a title slide and 3–12 content slides in a 16:9 presentation,
using colours from the repository design tokens copied at image build time.
It writes `/files/outputs/slides/<job-id>/<safe-title>.pptx` via a temporary file
and atomic rename. A finished deck is reused without another Gateway call.
Downloads belong to the Harness; the worker has no public file route.

Settings: `SW_KAFKA_BOOTSTRAP`, `SW_KAFKA_USERNAME`, `SW_KAFKA_PASSWORD`,
`SW_OIDC_ISSUER`, `SW_CLIENT_ID`, `SW_CLIENT_SECRET`, `SW_GATEWAY_URL`,
`SW_FILES_ROOT` (default `/files`), `SW_PURPOSE` (default `chat`) and `SW_TIER`
(default `1`). Password and client secret come from Kubernetes Secrets only.
The pod runs as user 10001 with a read-only root and the existing file volume
mounted read-write. The worker creates its own `outputs/slides/` folder with
mode 0755; it does not claim fsGroup ownership of the volume.

Both producers use a 10,000 ms message delivery timeout. Each publish waits for
its own delivery callback; it never purges other pending messages. A single surrounding JSON code fence is removed before deck validation.

## Tracing and replay (Stage 4)

The ConfigMap supplies `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_PROTOCOL`
(`http/protobuf`), `OTEL_EXPORTER_OTLP_ENDPOINT` and
`OTEL_TRACES_SAMPLER` (`parentbased_always_on`). An empty or unset endpoint
leaves tracing off: no provider or exporter is created. Health is excluded.
Spans export through a batch processor with a five-second export timeout;
export failures do not fail requests. Only the fixed attribute list is exported;
events, exception details and status descriptions are removed (an explicit error
code may remain). No database instrumentation is installed.

Each package instruments its own HTTP client, never every client globally.
Kafka sends and receives propagate W3C `traceparent` and `tracestate` headers.
Audit events include the current nonzero trace id when there is one.
Open a trace from Audit in the Admin Console after deploying the merged stage.
Jaeger stores traces in memory; restarting it clears traces but keeps audit rows.

Results and audit events derive their UUID v5 ids from the incoming event id,
event type and status. A failed result and completed replay have different ids;
repeated completed requests keep the same ids and reuse the finished file.
