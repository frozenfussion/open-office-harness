# QUICK GUIDE

1. **Set up the databases, sign-in and Kafka secrets.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. No password is needed. This creates the databases and saves private test settings. Run platform apply and realm sync first. Existing credentials are kept.

   ```bash
   cd ~/projects/worktrees/stage-3-part-a
   bash install/66-harness-api-setup.sh
   ```

   Good result: `DONE`. Test settings are saved in `~/.config/ooh/harness-api-test.env`, mode 600. Never paste or print that file. For the combined stage deployment, use `cd ~/projects/worktrees/stage-3` instead; after acceptance use `cd ~/projects/open-office-harness`.

2. **Run the builder checks.**

   Type this in your harness terminal, in the plain shell. No password is needed. This loads only the private test database settings and checks the service. Run it after setup prints `DONE`.

   ```bash
   cd ~/projects/worktrees/stage-3-part-a/services/harness-api
   set +x
   set -a
   source "$HOME/.config/ooh/harness-api-test.env"
   set +a
   uv sync --frozen
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest
   ```

   Good result: both Ruff checks pass and pytest has no failures or skips. Database protection checks run as the owner and app roles. Storage checks use a shared transaction that is always rolled back; a separate connection then verifies that none of that test user's conversations or messages remain. Without the two `HA_TEST_DB_*` settings, database checks are explicitly skipped; that is not a full pass.

3. **Deploy the image.**

   First wait for the Harness API image workflow to be green. Claude opens [package settings](https://github.com/users/frozenfussion/packages/container/ooh-harness-api/settings) on Aziz's PC; Aziz chooses **Change visibility → Public**. The workflow tests the image with a read-only root, without uv, as user 10001 before publishing it.

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. No password is needed. This deploys the image for the current commit, runs migrations, and waits for that revision to be ready.

   ```bash
   cd ~/projects/worktrees/stage-3
   bash install/67-harness-api-deploy.sh "$(git rev-parse --short=12 HEAD)"
   ```

   Good result: `Running image: ...` and `DONE`. The image must have been built for that commit. For a different built commit, pass its first 12 hexadecimal characters. Conversation data is kept.

4. **Check status and which image is running.**

   Type this in your harness terminal, in the plain shell. The folder doesn't matter for this command. No password is needed. This shows the image and ready replica count.

   ```bash
   kubectl -n ooh-apps get deployment harness-api -o wide
   ```

   Good result: one ready replica and the expected image tag.

5. **Read application logs.**

   Type this in your harness terminal, in the plain shell. The folder doesn't matter for this command. No password is needed. This reads recent JSON log lines.

   ```bash
   kubectl -n ooh-apps logs deployment/harness-api -c harness-api --tail=100
   ```

   Logs identify API failures with fixed event names and codes (and a tier for stream failures or budget fallback). Kafka failures include only fixed codes and validated correlation ids. Server log lines keep the logger name, a fixed message category and the exception type when available; exception messages and traceback text are excluded. They contain no prompts, answers, user IDs or credentials. Access logs are disabled.

6. **Read migration logs if deployment stops.**

   Type this in your harness terminal, in the plain shell. The folder doesn't matter for this command. No password is needed. This reads the current pod's migration result.

   ```bash
   kubectl -n ooh-apps logs deployment/harness-api -c migrate --tail=100
   ```

   Good result: `migrations_complete`. If it says `migration_failed`, inspect the database settings and readiness privately, then run deployment again. Do not edit an applied migration.

7. **Restart.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. The folder doesn't matter for this command. No password is needed. This replaces the pod and reruns the safe migration check.

   ```bash
   kubectl -n ooh-apps rollout restart deployment/harness-api
   ```

   Repeat the status step until one replica is ready.

8. **Stop.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. The folder doesn't matter for this command. No password is needed. This stops the API; its stored conversations stay in PostgreSQL.

   ```bash
   kubectl -n ooh-apps scale deployment/harness-api --replicas=0
   ```

   Good result: the Deployment is scaled. Chat is unavailable until started again.

9. **Start again.**

   Type this in your harness terminal, in the plain shell. Claude runs it while Aziz watches. The folder doesn't matter for this command. No password is needed. This starts the API again.

   ```bash
   kubectl -n ooh-apps scale deployment/harness-api --replicas=1
   ```

   Repeat the status step until one replica is ready.

10. **After a server reboot.** Allow five minutes, then check status. Kubernetes starts the API automatically if it had one replica before reboot. Claude runs the platform, Control Centre and Stage 2 checks while Aziz watches.

    Type this in your harness terminal, in the plain shell. No password is needed. This checks the combined stage after reboot.

    ```bash
    cd ~/projects/worktrees/stage-3
    bash install/40-check-platform.sh
    bash install/62-check-control-centre.sh
    bash install/70-check-stage-2.sh
    bash install/77-check-stage-3.sh "$(git rev-parse --short=12 HEAD)"
    ```

    Good result: each prints only passing checks and ends with `DONE`. Each run of the Stage 2 check makes short paid model calls. Aziz then signs in to the Workspace and checks chat and history.

## STOP messages

Neither script needs sudo. Resolve the named problem and run the same script again; existing credentials and data are kept.

| STOP text | What to do |
|---|---|
| invalid deployment value | Correct the named setting in `deploy/values/do.env`. |
| missing tool | Finish server setup. |
| platform/apps namespace missing | Finish platform deployment. |
| PostgreSQL is not Ready | Inspect platform PostgreSQL readiness. |
| database resources are not ready | Inspect Database and DatabaseRole status. |
| existing secret has unexpected credentials / database passwords have an unexpected format | Have the maintainer inspect the Secret privately; do not replace it. |
| PostgreSQL service has no valid ClusterIP | Inspect Service `ooh-pg-rw`. |
| could not read Harness client secret | Inspect Keycloak readiness and bootstrap access, then retry. |
| Harness client secret changed | Ask the maintainer before replacing `harness-api-oidc`. |
| existing application database credentials differ | Ask the maintainer to inspect role and application Secrets privately before replacing anything. |
| KafkaUser harness-api not ready; re-run 30 | Run platform apply, wait for Strimzi, then repeat setup. |
| Kafka password changed in Strimzi | Ask the maintainer to inspect credentials privately; do not replace them. |
| database setup failed | Inspect PostgreSQL readiness and retry setup. |
| usage | Setup takes no arguments. Deployment takes at most one 12-character image tag. |
| image tag must be the first 12 characters | Supply the first 12 hexadecimal characters of a built commit. |
| image not built yet | Wait for the workflow for that commit, or run it on demand. |
| image not found or not public | Check the workflow is green; Aziz switches the package to Public. |
| registry is unreachable / registry check failed / registry returned an invalid token | Check registry availability and retry. |
| configuration hash could not be made | Check sha256sum is available and retry deployment. |
| required application secret missing | Run `install/66-harness-api-setup.sh`. |
| new Harness API revision is not Ready | Inspect migration logs, image visibility and pod status. |
| current revision or migrations could not be verified | Inspect the Deployment, its ReplicaSet and pods, then retry. |
| Harness API deployment failed | Inspect migration logs and pod readiness, then retry deployment. |

## API and storage

Every `/api` route requires a signed, unexpired Keycloak user token with audience `ooh-harness-api`, issuer `HA_OIDC_ISSUER` and non-empty `sub`. Health alone is public and checks PostgreSQL. Unknown inputs return `400` JSON without echoing the input. Jobs, downloads and live job events are built. Uploads return `503 not_built_yet` with "Uploads are not built yet."

`GET /api/me` first observes the verified user's profile through the Control Centre, then reads rights and allowed skill titles. Its answer includes `access`: `approved`, `pending`, `rejected` or `closed` (new requests are temporarily full). The observe call uses the Harness service token and the exact user `sub`. Only the signed token supplies profile fields: name, email, organisation and access reason are trimmed and limited to 200, 320, 100 and 300 characters respectively; missing or non-string values become null. `is_admin` is true only when the verified token's `realm_access.roles` list contains `ooh-admin`. An observe failure or invalid status returns `503 rights_unavailable` before any rights call. The Control Centre owns approval and blocks grants for unapproved people; the Harness does not decide access. Other Harness routes are unchanged.

`GET /api/me` also returns the token's user ID and name, plus rights and allowed skill titles from the Control Centre. `chat_tier_titles` passes through the Control Centre's tier-to-title map, with string tier keys; the Workspace uses it for model names. The Control Centre selects the active main entry by lowest priority then creation time; no title is invented by the Harness, and a missing title falls back to the tier label in the Workspace. It also passes through `chat_tier_thinking_switch` and `requestable_tiers` from the Control Centre. Each requestable tier has a title and `requested` state (`pending`, `rejected` or null); the Control Centre excludes tier 99 and granted tiers and owns the seven-day rejection wait. No supplied body or query can change the user's ID. Conversations belong to that ID; other users see `404`. The conversation list orders by updated time, then ID, newest first. It defaults to 20 rows and accepts `limit=1..100`; `before` is the ID of an owned conversation from the preceding page (the spec author agreed to this pagination during the build).

Messages go to the Gateway as purpose `chat`, by tier, without any model identifier or provider setting. The optional `thinking` field is a strict boolean, default true; it is forwarded unchanged on the initial call and budget fallback. The Gateway reports whether the answering model applied the setting via required boolean `thinking_applied`; a missing or non-boolean value is an unexpected answer, never a default false. The lowest allowed tier is used when omitted. Rights are checked afresh for the selected tier and again before a budget fallback. Failed rights calls fail closed. Allowed skills are intersected with the user's rights; only locally bundled schemas become tools. The schema copy is tested byte for byte against the contract. A tool call rechecks the user's allowed skills and validates arguments against its input schema. The Harness creates a job, audits the right check, publishes the request (or approval), sends a chat `job` card and returns a tool result to the model. At most two tool rounds run. Follow-ups are pinned to the first entry; failures keep an already-started job and explain that the model could not finish its answer. A third tool round ends with "Tool limit reached for this message." A queue failure marks the job failed with `queue_unavailable`.

Every streamed chat Gateway call prepends one system message from `HA_SYSTEM_PROMPT`, including budget fallback. The default is "You are the assistant in Open Office Harness. Always reply in the same language as the user's latest message." The ConfigMap `harness-api-config` supplies this setting; edit `deploy/apps/harness-api/configmap.yaml`, then run `install/67-harness-api-deploy.sh` with the existing image tag to update it without rebuilding the image. The deployment uses a hash of the rendered ConfigMap to restart the pod when settings change. A live ConfigMap edit is overwritten by the next deploy. An explicitly empty value sends no system message. The prompt is never logged or stored as a conversation message.

The history window is read before storing the new user message: the last 20 non-empty `completed` messages, oldest first, trimmed to start with a user message. The new question is appended once. A user's question is stored as `completed`; the initial title is its first 60 characters. After the first assistant answer stored as `completed`, and only while the conversation still has the default title, the Harness attempts one non-streamed title call on the tier that answered. Rights are rechecked for the original user, while the Gateway user ID is `title-<sub>` so the title does not consume that user's rate allowance; model budget and cost still count. A fixed 20-second limit covers the title work and the stream closes after the title call or that limit. It sends `thinking: false`, ignores any thinking in the non-streamed reply, and uses only answer content for a title. It uses its own fixed title instruction instead of `HA_SYSTEM_PROMPT`, followed by the first question and the first completed answer (each cut to 2000 characters), with no tools. The returned title is trimmed, stripped of surrounding quotes and a final full stop, and cut to 60 characters. Updating the title leaves `updated_at` unchanged. Failure keeps the initial title and logs `title_failed` with a safe code, never title or conversation text. Later answers do not retry; failed and `tool_requested` answers do not trigger title generation. Assistant content is appended after streaming, including partial text with outcome `failed` after a broken stream or browser disconnect. Messages cannot be updated or removed, even as the owner. All tables refuse DELETE and TRUNCATE. The application role has only SELECT/INSERT on messages and SELECT/INSERT/UPDATE on conversations; it cannot edit the migration journal.

SSE uses JSON `data:` lines, without `event:` lines. `thinking` events carry thinking text before or between answer `delta` events, never after `completed`. Empty thinking strings and unknown stream event types are ignored, allowing Gateway-first, Harness-second, Workspace-last deployment. The Harness stores only the first 100,000 characters of thinking per message; later thinking still streams to the browser. Thinking text is concatenated and stored separately in the assistant message's nullable `thinking` column, including partial thinking after a stream failure or disconnect; it is returned in conversation history. Existing messages have null thinking. Visible thinking text is never logged or used as model context. Separately, the Gateway's opaque `reasoning_state` is stored privately with its entry identity in `messages.reasoning_state` and included on assistant history messages sent to the Gateway (binding spec clarification, section 14 row 5). It is never returned by any route, logged or published to Kafka. The adapter decides whether a state's entry matches; follow-ups within one tool turn remain pinned. The forward migration adds the column without changing the app role's SELECT/INSERT-only message permissions. The answer stream ends with `completed` or `failed`; when the first completed answer produces a title, one final `title` event follows `completed`, with `conversation_id` and `title`. JSON errors are returned before any stream byte. Responses set `Cache-Control: no-store` and `X-Accel-Buffering: no`. Completion includes message ID, tier, model title, token usage, `thinking_applied` and a nullable fallback note. The answer is complete at that event; a later title event can still arrive on the same stream. The boolean `thinking_applied` remains live SSE metadata only; the new `thinking` column stores text, not that flag. Conversation history includes outcome and metadata. Chat text is passed as text; the Workspace owns its rendering.

| Code | Browser message / action |
|---|---|
| `no_tier` | You have no chat tier yet. An admin can grant one. |
| `tier_not_allowed` | You don't have tier N. An admin can grant it. |
| `rights_unavailable` | Rights could not be checked. Try again. |
| `no_model` | No model is set up for tier N yet. An admin can add one. |
| `rate_limited` | You are sending messages too fast for tier N. Wait a minute. |
| `budget_exceeded` | Use the lowest allowed lower tier, with a note; otherwise: Tier N has used its daily budget. Try again tomorrow or ask an admin. |
| `unavailable` | The model did not answer. Try again. A storage failure says conversation storage is unavailable. |

`POST /api/tier-requests` accepts `{tier, reason?}` with a positive integer tier and optional string/null reason (at most 300 characters). It supplies the verified user ID and forwards the request with the Harness service token; callers cannot choose another user. Only the Control Centre decides eligibility. Success is 201 `{id,status:"pending"}`. Errors preserve status/code: 403 `not_approved`, 400 `tier_not_requestable`, 409 `already_requested` or `too_soon`, 429 `too_many_requests`; unavailable or malformed Control Centre responses fail closed with 503 `rights_unavailable`. The reason is never logged. A repeat request before seven days returns `too_soon`: "You can ask for this model again 7 days after the last answer." A rejected tier may be requested again after seven days and each user may have at most 20 pending requests, as enforced by the Control Centre.

## Configuration and builds

The ConfigMap supplies `HA_OIDC_ISSUER`, `HA_OIDC_AUDIENCE`, `HA_CLIENT_ID`, `HA_CONTROL_CENTRE_URL` (port 8080), `HA_GATEWAY_URL` and `HA_SYSTEM_PROMPT`. Secret `harness-api-db` supplies `HA_DB_CONNECTION` to the app and `HA_DB_MIGRATE_CONNECTION` only to the migration container. Secret `harness-api-oidc` supplies `HA_CLIENT_SECRET`. Keys stay in the Control Centre and never enter the Harness. Service tokens are cached until 30 seconds before expiry; realm signing keys are cached for five minutes and refreshed for an unknown key ID at most once every 30 seconds, including failed fetches. Outgoing redirects are refused.

Python is 3.14.10. The image uses `python:3.14.10-slim-trixie` for both stages; uv 0.13.7 is digest-pinned and present only in the build stage. The runtime uses user 10001, a read-only root, disabled bytecode writes and unbuffered stdout. `/tmp` is a bounded memory volume. The workflow builds, loads, checks the runtime, then pushes its 12-character commit tag. Runtime dependencies and all transitive versions are fixed in `uv.lock`.

The migration command applies numbered SQL files in order under a transaction advisory lock. SHA-256 checksums prevent changed applied migrations. It accepts only databases `harness` and `harness_test`; the journal is append-only. The in-process Kafka consumer uses group `harness-api`, handles `skill.results` and `approvals.decided`, inserts `processed_events` in the same transaction as the job update and ignores duplicate and unknown events. Non-fatal Kafka errors keep polling. After a stopped consumer or failed dead-letter publish, the consumer is rebuilt after five seconds; chat readiness depends only on the database. Invalid messages go straight to their dead-letter topic; other failures retry after 1, 5 and 15 seconds. A terminal job never changes from a later result. Approval rechecks rights and fails closed with `right_removed` or `rights_unavailable`. The consumer uses no real Kafka in unit tests.

## Jobs, files and Kafka

`GET /api/jobs?limit=20&before=<job-id>` lists only this user's jobs, ordered by
creation time then id, newest first. `before` must identify this user's job.
Rows carry title, label (topic cut to 80 characters), state, times, output and
error. The Jobs panel reloads on each SSE reconnect. `GET /api/events` sends
user-scoped `job.*` events in the existing contract shape (`correlation_id`
is the job id), with `: keep-alive` comments every 15 seconds. The stream closes when its verified token expires; the Workspace reconnects with a fresh token.

`GET /api/jobs/{job_id}/file` streams only this user's completed job file under
`/files/outputs/` as an attachment. Unknown jobs, other owners, missing files,
unfinished jobs and path escapes return 404. The PVC is read-only in this API.
Files remain on the volume across restarts and reboots; nothing is deleted.

`POST /api/skill-requests` accepts `{skill,reason?}`, supplies the verified user
id, and preserves the Control Centre's success and error status/code.
`/api/me.requestable_skills` contains `{name,title,description,requested}`.
The observe call marks service accounts from a verified `client_id` claim or a
`preferred_username` beginning `service-account-`.

Stored user and completed assistant text is published to `chat.messages`, cut
to 20,000 characters; empty text is omitted. Publishing runs in retained asynchronous tasks with a
12-second limit, so broker failure cannot delay chat. Both Kafka producers use
a 10-second message delivery timeout and wait for each message's own delivery
callback, without purging other messages. Harness sends use a dedicated pool of
four threads, separate from consumer polling. When all four send slots are busy,
chat events are skipped with `chat_publish_failed`; they are not queued. A send
keeps its slot until the underlying thread finishes, even if its awaiting chat
task times out. Audit publish failures are logged and never fail a job whose
request was queued successfully. The turn's user message id is its correlation id, also used on chat and
title Gateway calls. Job events and worker calls use the job's own id.

Configuration adds `HA_KAFKA_BOOTSTRAP`, `HA_KAFKA_USERNAME`,
`HA_KAFKA_PASSWORD` (Secret `harness-api-kafka`) and `HA_FILES_ROOT=/files`.
Migration `0003_jobs.sql` adds jobs, insert-only processed events and private
reasoning state. Applied migrations are never edited. Deploy and check only
from the merged Stage 3 worktree after Parts B–D are present.
